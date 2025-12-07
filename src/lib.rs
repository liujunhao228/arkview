use pyo3::prelude::*;
use rayon::prelude::*;
use std::collections::HashSet;
use std::fs;
use std::io::Read;
use std::path::Path;
use image::GenericImageView;

/// 支持的图像文件扩展名
const IMAGE_EXTENSIONS: &[&str] = &[
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".webp", ".ico",
];

/// ZIP文件扫描器
///
/// 分析ZIP文件内容，检查是否仅包含图像文件，
/// 并提供文件元数据和图像统计信息。
#[pyclass]
pub struct ZipScanner {
    /// 支持的图像扩展名集合
    image_extensions: HashSet<String>,
}

#[pymethods]
impl ZipScanner {
    /// 创建新的ZipScanner实例
    #[new]
    fn new() -> Self {
        let extensions = IMAGE_EXTENSIONS
            .iter()
            .map(|ext| ext.to_lowercase())
            .collect();
        
        ZipScanner {
            image_extensions: extensions,
        }
    }

    /// 检查文件名是否为支持的图像格式
    fn is_image_file(&self, filename: &str) -> bool {
        if filename.is_empty() || filename.ends_with('/') {
            return false;
        }
        
        filename
            .rfind('.')
            .map(|dot_pos| {
                let ext = &filename[dot_pos..].to_lowercase();
                self.image_extensions.contains(ext)
            })
            .unwrap_or(false)
    }

    /// 分析ZIP文件内容
    ///
    /// 返回元组包含：
    /// - 是否仅包含图像文件
    /// - 图像成员列表（可选）
    /// - 最后修改时间（Unix时间戳）
    /// - 文件大小（字节）
    /// - 图像文件数量
    fn analyze_zip(
        &self,
        zip_path: &str,
        collect_members: Option<bool>,
    ) -> PyResult<(bool, Option<Vec<String>>, Option<f64>, Option<u64>, u32)> {
        let should_collect = collect_members.unwrap_or(true);
        let path = Path::new(zip_path);

        // 验证文件可访问性
        if !path.exists() {
            return Ok((false, None, None, None, 0));
        }

        // 获取文件元数据
        let metadata = match fs::metadata(path) {
            Ok(m) => m,
            Err(_) => return Ok((false, None, None, None, 0)),
        };

        // 提取修改时间和文件大小
        let mod_time = metadata
            .modified()
            .ok()
            .and_then(|t| {
                t.duration_since(std::time::UNIX_EPOCH)
                    .ok()
                    .map(|d| d.as_secs_f64())
            });
        
        let file_size = metadata.len();

        // 限制处理大文件（500MB）
        const MAX_FILE_SIZE: u64 = 500 * 1024 * 1024;
        if file_size > MAX_FILE_SIZE {
            return Ok((false, None, mod_time, Some(file_size), 0));
        }

        // 打开并验证ZIP文件
        let file = match fs::File::open(path) {
            Ok(f) => f,
            Err(_) => return Ok((false, None, mod_time, Some(file_size), 0)),
        };

        let mut zip = match zip::ZipArchive::new(file) {
            Ok(z) => z,
            Err(_) => return Ok((false, None, mod_time, Some(file_size), 0)),
        };

        let total_entries = zip.len();
        
        // 限制处理过多条目
        const MAX_ENTRIES: usize = 10000;
        if total_entries > MAX_ENTRIES {
            return Ok((false, None, mod_time, Some(file_size), 0));
        }

        // 处理ZIP条目
        let mut image_members = if should_collect {
            Vec::with_capacity(total_entries.min(100))
        } else {
            Vec::new()
        };
        
        let mut image_count = 0u32;
        let mut has_at_least_one_file = false;

        // 设置处理超时（15秒）
        let start_time = std::time::Instant::now();
        const TIMEOUT: std::time::Duration = std::time::Duration::from_secs(15);

        // 检查条目内容
        const ENTRY_LIMIT: usize = 1000;
        let check_limit = total_entries.min(ENTRY_LIMIT);
        
        for i in 0..check_limit {
            // 检查超时
            if start_time.elapsed() > TIMEOUT {
                return Ok((false, None, mod_time, Some(file_size), image_count));
            }

            let file = match zip.by_index(i) {
                Ok(f) => f,
                Err(_) => continue,
            };

            if file.is_dir() {
                continue;
            }

            has_at_least_one_file = true;
            let filename = file.name();

            if self.is_image_file(filename) {
                image_count += 1;
                if should_collect {
                    image_members.push(filename.to_string());
                }
            } else {
                // 发现非图像文件
                return Ok((false, None, mod_time, Some(file_size), image_count));
            }
        }

        // 如果条目数超过限制但都是图像，仍视为无效
        if total_entries > ENTRY_LIMIT {
            return Ok((false, None, mod_time, Some(file_size), image_count));
        }

        // 确定ZIP文件有效性
        let is_valid = has_at_least_one_file && image_count > 0;
        let members = if is_valid && should_collect {
            Some(image_members)
        } else {
            None
        };

        Ok((is_valid, members, mod_time, Some(file_size), image_count))
    }

    /// 批量分析ZIP文件
    fn batch_analyze_zips(
        &self,
        zip_paths: Vec<String>,
        collect_members: Option<bool>,
    ) -> PyResult<Vec<(String, bool, Option<Vec<String>>, Option<f64>, Option<u64>, u32)>> {
        let should_collect = collect_members.unwrap_or(true);
        
        let results = zip_paths
            .into_par_iter()
            .map(|zip_path| {
                match self.analyze_zip(&zip_path, Some(should_collect)) {
                    Ok((is_valid, members, mod_time, file_size, image_count)) => {
                        (zip_path, is_valid, members, mod_time, file_size, image_count)
                    }
                    Err(_) => (zip_path, false, None, None, None, 0)
                }
            })
            .collect();
        
        Ok(results)
    }
}

/// 图像处理器
///
/// 提供图像处理和验证功能
#[pyclass]
pub struct ImageProcessor;

#[pymethods]
impl ImageProcessor {
    /// 创建新的ImageProcessor实例
    #[new]
    fn new() -> Self {
        ImageProcessor
    }

    /// 从图像数据生成缩略图
    fn generate_thumbnail(
        &self,
        image_data: &[u8],
        max_width: u32,
        max_height: u32,
        fast_mode: bool,
    ) -> PyResult<Vec<u8>> {
        // 加载图像
        let img = image::load_from_memory(image_data)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyIOError, _>(e.to_string()))?;

        let (width, height) = img.dimensions();
        let aspect_ratio = width as f32 / height as f32;

        // 计算缩略图尺寸
        let new_height = max_height;
        let new_width = ((new_height as f32) * aspect_ratio) as u32;
        let final_width = new_width.min(max_width);
        let final_height = (final_width as f32 / aspect_ratio) as u32;

        // 调整图像尺寸
        let img = if fast_mode {
            img.thumbnail(final_width, final_height)
        } else {
            img.resize(final_width, final_height, image::imageops::FilterType::Lanczos3)
        };

        // 编码为PNG格式
        let mut thumb_data = Vec::new();
        img.write_to(&mut std::io::Cursor::new(&mut thumb_data), image::ImageFormat::Png)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyIOError, _>(e.to_string()))?;

        Ok(thumb_data)
    }

    /// 从ZIP文件中提取图像
    fn extract_image_from_zip(
        &self,
        zip_path: &str,
        member_name: &str,
    ) -> PyResult<Vec<u8>> {
        let file = fs::File::open(zip_path)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyIOError, _>(e.to_string()))?;

        let mut zip = zip::ZipArchive::new(file)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyIOError, _>(e.to_string()))?;

        let mut file = zip
            .by_name(member_name)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyIOError, _>(e.to_string()))?;

        let mut data = Vec::new();
        file.read_to_end(&mut data)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyIOError, _>(e.to_string()))?;

        Ok(data)
    }

    /// 验证图像数据格式
    fn validate_image_format(&self, image_data: &[u8]) -> PyResult<bool> {
        match image::load_from_memory(image_data) {
            Ok(_) => Ok(true),
            Err(_) => Ok(false),
        }
    }
}

/// 格式化文件大小为人类可读的字符串
#[pyfunction]
fn format_size(size_bytes: u64) -> String {
    const KB: f64 = 1024.0;
    const MB: f64 = KB * 1024.0;
    const GB: f64 = MB * 1024.0;

    match size_bytes {
        n if n < 1024 => format!("{} B", n),
        n if n < 1024 * 1024 => format!("{:.1} KB", n as f64 / KB),
        n if n < 1024 * 1024 * 1024 => format!("{:.1} MB", n as f64 / MB),
        n => format!("{:.1} GB", n as f64 / GB),
    }
}

/// Python模块初始化
#[pymodule]
fn arkview_core(_py: Python, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<ZipScanner>()?;
    m.add_class::<ImageProcessor>()?;
    m.add_function(wrap_pyfunction!(format_size, m)?)?;
    Ok(())
}
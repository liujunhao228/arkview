use pyo3::prelude::*;
use rayon::prelude::*;
use std::collections::HashSet;
use std::fs;
use std::io::Read;
use std::path::Path;
use image::GenericImageView;

/// 支持的图像文件扩展名列表
const IMAGE_EXTENSIONS: &[&str] = &[
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".webp", ".ico",
];

/// ZIP文件扫描器
/// 
/// 用于分析ZIP文件以确定它是否只包含图像文件，
/// 并收集相关信息如修改时间、文件大小和图像计数。
#[pyclass]
pub struct ZipScanner {
    /// 存储支持的图像扩展名的小写版本
    image_extensions: HashSet<String>,
}

#[pymethods]
impl ZipScanner {
    /// 创建一个新的ZipScanner实例
    #[new]
    fn new() -> Self {
        let mut extensions = HashSet::new();
        for ext in IMAGE_EXTENSIONS {
            extensions.insert(ext.to_lowercase());
        }
        ZipScanner {
            image_extensions: extensions,
        }
    }

    /// 判断给定文件名是否为图像文件
    /// 
    /// # 参数
    /// * `filename` - 要检查的文件名
    /// 
    /// # 返回值
    /// 如果文件是图像文件则返回true，否则返回false
    fn is_image_file(&self, filename: &str) -> bool {
        // 空文件名或目录不被视为图像文件
        if filename.is_empty() || filename.ends_with('/') {
            return false;
        }
        
        // 查找最后一个点以获取文件扩展名
        if let Some(dot_pos) = filename.rfind('.') {
            let ext = &filename[dot_pos..].to_lowercase();
            return self.image_extensions.contains(ext);
        }
        false
    }

    /// 分析ZIP文件以确定它是否只包含图像文件
    /// 
    /// # 参数
    /// * `zip_path` - ZIP文件的路径
    /// * `collect_members` - 是否收集ZIP成员列表（可选，默认为true）
    /// 
    /// # 返回值
    /// 返回一个元组，包含以下元素：
    /// * `is_valid` - ZIP文件是否只包含图像文件
    /// * `members` - 图像文件成员列表（如果collect_members为true且ZIP有效）
    /// * `mod_time` - 文件最后修改时间（Unix时间戳）
    /// * `file_size` - 文件大小（字节）
    /// * `image_count` - 图像文件数量
    /// 
    /// # 错误处理
    /// 如果发生任何错误（如文件不存在、无法读取等），函数会返回适当的默认值而不是传播错误
    fn analyze_zip(
        &self,
        zip_path: &str,
        collect_members: Option<bool>,
    ) -> PyResult<(bool, Option<Vec<String>>, Option<f64>, Option<u64>, u32)> {
        let should_collect = collect_members.unwrap_or(true);
        let path = Path::new(zip_path);

        // 检查文件是否存在
        if !path.exists() {
            return Ok((false, None, None, None, 0));
        }

        // 获取文件元数据
        let metadata = match fs::metadata(path) {
            Ok(m) => m,
            Err(_) => return Ok((false, None, None, None, 0)),
        };

        // 获取文件修改时间
        let mod_time = metadata
            .modified()
            .ok()
            .and_then(|t| {
                t.duration_since(std::time::UNIX_EPOCH)
                    .ok()
                    .map(|d| d.as_secs_f64())
            });
            
        // 获取文件大小
        let file_size = metadata.len();

        // 检查文件是否过大以避免处理极大的归档文件
        // 500MB限制是为了安全性，可以调整
        if file_size > 500 * 1024 * 1024 { 
            return Ok((false, None, mod_time, Some(file_size), 0));
        }

        // 对于可能有问题的文件，先尝试读取一小部分内容
        let file = match fs::File::open(path) {
            Ok(f) => f,
            Err(_) => return Ok((false, None, mod_time, Some(file_size), 0)),
        };

        // 检查我们能否读取文件开头以验证文件是否可访问
        let mut buffer = [0; 4];  // 只读取前4个字节
        let mut file_clone = file.try_clone().unwrap_or(file);
        match file_clone.read_exact(&mut buffer) {
            Ok(_) => {
                // 文件可读，继续处理ZIP打开
                drop(file_clone); // 关闭克隆的文件句柄
            },
            Err(_) => {
                // 无法读取文件，可能是损坏或被锁定
                return Ok((false, None, mod_time, Some(file_size), 0));
            }
        }

        // 现在尝试打开ZIP文件
        let file = match fs::File::open(path) {
            Ok(f) => f,
            Err(_) => return Ok((false, None, mod_time, Some(file_size), 0)),
        };

        let mut zip = match zip::ZipArchive::new(file) {
            Ok(z) => z,
            Err(_) => return Ok((false, None, mod_time, Some(file_size), 0)),
        };

        let total_entries = zip.len();

        // 检查条目数量是否过多以避免处理包含大量条目的归档文件
        if total_entries > 10000 {
            return Ok((false, None, mod_time, Some(file_size), 0));
        }

        // 初始化变量以存储图像成员和计数
        let mut image_members = if should_collect {
            Vec::with_capacity(std::cmp::min(total_entries, 100))
        } else {
            Vec::new()
        };
        
        let mut image_count = 0u32;
        let mut has_at_least_one_file = false;

        // 启动计时以防止处理过程中挂起
        use std::time::Instant;
        let start_time = Instant::now();
        // 最大处理时间为15秒
        let max_processing_time = std::time::Duration::from_secs(15); 

        // 检查所有文件是否都是图像（遇到第一个非图像文件时提前退出）
        // 限制处理前1000个条目以避免处理包含大量文件的归档
        let limit = std::cmp::min(total_entries, 1000);
        for i in 0..limit {
            // 检查是否超过了最大处理时间限制
            if start_time.elapsed() > max_processing_time {
                eprintln!("Processing time exceeded for {}", zip_path);
                return Ok((false, None, mod_time, Some(file_size), image_count));
            }

            // 获取ZIP中的第i个文件
            let file = match zip.by_index(i) {
                Ok(f) => f,
                Err(_) => continue,
            };

            // 跳过目录
            if file.is_dir() {
                continue;
            }

            has_at_least_one_file = true;
            let filename = file.name();

            // 检查文件是否为图像
            if self.is_image_file(filename) {
                image_count += 1;
                if should_collect {
                    image_members.push(filename.to_string());
                }
            } else {
                // 找到非图像文件，归档无效
                return Ok((false, None, mod_time, Some(file_size), image_count));
            }
        }

        // 如果达到了限制但没有找到非图像文件，
        // 检查是否有更多未处理的条目
        if limit == 1000 && total_entries > 1000 {
            return Ok((false, None, mod_time, Some(file_size), image_count));
        }

        // 确定ZIP文件是否有效（至少有一个文件且都是图像）
        let is_valid = has_at_least_one_file && image_count > 0;
        let members = if is_valid && should_collect {
            Some(image_members)
        } else {
            None
        };

        Ok((is_valid, members, mod_time, Some(file_size), image_count))
    }

    /// 批量分析多个ZIP文件
    /// 
    /// # 参数
    /// * `zip_paths` - ZIP文件路径列表
    /// * `collect_members` - 是否收集ZIP成员列表（可选，默认为true）
    /// 
    /// # 返回值
    /// 返回一个元组向量，每个元组包含：
    /// * ZIP文件路径
    /// * ZIP文件是否只包含图像文件
    /// * 图像文件成员列表（如果collect_members为true且ZIP有效）
    /// * 文件最后修改时间（Unix时间戳）
    /// * 文件大小（字节）
    /// * 图像文件数量
    fn batch_analyze_zips(
        &self,
        zip_paths: Vec<String>,
        collect_members: Option<bool>,
    ) -> PyResult<Vec<(String, bool, Option<Vec<String>>, Option<f64>, Option<u64>, u32)>> {
        let should_collect = collect_members.unwrap_or(true);
        
        // 使用rayon进行并行处理
        let results: Vec<(String, bool, Option<Vec<String>>, Option<f64>, Option<u64>, u32)> = zip_paths
            .into_par_iter()
            .map(|zip_path| {
                // 对每个ZIP文件进行分析
                let analysis_result = self.analyze_zip(&zip_path, Some(should_collect));
                match analysis_result {
                    Ok((is_valid, members, mod_time, file_size, image_count)) => {
                        (zip_path, is_valid, members, mod_time, file_size, image_count)
                    }
                    // 如果分析过程中出现错误，则返回默认值
                    Err(_) => {
                        (zip_path, false, None, None, None, 0)
                    }
                }
            })
            .collect();
        
        Ok(results)
    }
}

/// 图像处理器
/// 
/// 用于生成缩略图、从ZIP文件中提取图像以及验证图像格式。
#[pyclass]
pub struct ImageProcessor {
    // 用于操作期间的缓存（目前未使用）
}

#[pymethods]
impl ImageProcessor {
    /// 创建一个新的ImageProcessor实例
    #[new]
    fn new() -> Self {
        ImageProcessor {}
    }

    /// 从图像数据生成缩略图
    /// 
    /// # 参数
    /// * `image_data` - 原始图像数据
    /// * `max_width` - 缩略图最大宽度
    /// * `max_height` - 缩略图最大高度
    /// * `fast_mode` - 是否使用快速采样算法
    /// 
    /// # 返回值
    /// 返回PNG格式的缩略图数据
    /// 
    /// # 错误处理
    /// 如果图像加载或处理失败，将返回PyIOError异常
    fn generate_thumbnail(
        &self,
        image_data: &[u8],
        max_width: u32,
        max_height: u32,
        fast_mode: bool,
    ) -> PyResult<Vec<u8>> {
        // 从内存中加载图像
        let img = image::load_from_memory(image_data)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyIOError, _>(e.to_string()))?;

        // 计算图像的宽高比
        let (width, height) = img.dimensions();
        let aspect_ratio = width as f32 / height as f32;

        // 根据高度计算新宽度
        let new_height = max_height;
        let new_width = ((new_height as f32) * aspect_ratio) as u32;

        // 确保宽度不超过最大宽度
        let final_width = if new_width > max_width { max_width } else { new_width };
        let final_height = (final_width as f32 / aspect_ratio) as u32;

        // 根据fast_mode选择不同的重采样算法
        let img = if fast_mode {
            // 使用更快的采样算法
            img.thumbnail(final_width, final_height)
        } else {
            // 使用高质量的Lanczos3算法
            img.resize(final_width, final_height, image::imageops::FilterType::Lanczos3)
        };

        // 将缩略图写入PNG格式的数据缓冲区
        let mut thumb_data = Vec::new();
        img.write_to(&mut std::io::Cursor::new(&mut thumb_data), image::ImageFormat::Png)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyIOError, _>(e.to_string()))?;

        Ok(thumb_data)
    }

    /// 从ZIP文件中提取特定成员的图像数据
    /// 
    /// # 参数
    /// * `zip_path` - ZIP文件路径
    /// * `member_name` - 要提取的成员名称
    /// 
    /// # 返回值
    /// 返回提取的图像数据
    /// 
    /// # 错误处理
    /// 如果文件操作或ZIP处理失败，将返回PyIOError异常
    fn extract_image_from_zip(
        &self,
        zip_path: &str,
        member_name: &str,
    ) -> PyResult<Vec<u8>> {
        // 打开ZIP文件
        let file = fs::File::open(zip_path)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyIOError, _>(e.to_string()))?;

        // 创建ZIP归档对象
        let mut zip = zip::ZipArchive::new(file)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyIOError, _>(e.to_string()))?;

        // 获取指定名称的文件
        let mut file = zip
            .by_name(member_name)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyIOError, _>(e.to_string()))?;

        // 读取文件数据到缓冲区
        let mut data = Vec::new();
        file.read_to_end(&mut data)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyIOError, _>(e.to_string()))?;

        Ok(data)
    }

    /// 验证图像数据格式是否有效
    /// 
    /// # 参数
    /// * `image_data` - 要验证的图像数据
    /// 
    /// # 返回值
    /// 如果图像格式有效返回true，否则返回false
    fn validate_image_format(&self, image_data: &[u8]) -> PyResult<bool> {
        // 尝试从内存加载图像以验证格式
        match image::load_from_memory(image_data) {
            Ok(_) => Ok(true),
            Err(_) => Ok(false),
        }
    }
}

/// 将字节数格式化为人类可读的大小字符串
/// 
/// # 参数
/// * `size_bytes` - 字节数
/// 
/// # 返回值
/// 格式化后的大小字符串（例如："1.5 MB"）
#[pyfunction]
fn format_size(size_bytes: u64) -> String {
    if size_bytes < 1024 {
        format!("{} B", size_bytes)
    } else if size_bytes < 1024 * 1024 {
        format!("{:.1} KB", size_bytes as f64 / 1024.0)
    } else if size_bytes < 1024 * 1024 * 1024 {
        format!("{:.1} MB", size_bytes as f64 / (1024.0 * 1024.0))
    } else {
        format!("{:.1} GB", size_bytes as f64 / (1024.0 * 1024.0 * 1024.0))
    }
}

/// Python模块初始化函数
/// 
/// # 参数
/// * `_py` - Python解释器实例
/// * `m` - 模块对象
/// 
/// # 返回值
/// 成功时返回Ok(())，失败时返回PyErr
#[pymodule]
fn arkview_core(_py: Python, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<ZipScanner>()?;
    m.add_class::<ImageProcessor>()?;
    m.add_function(wrap_pyfunction!(format_size, m)?)?;
    Ok(())
}
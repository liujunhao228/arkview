use pyo3::prelude::*;
use std::collections::HashSet;
use std::fs;
use std::io::Read;
use std::path::Path;
use image::io::Reader as ImageReader;
use image::GenericImageView;

const IMAGE_EXTENSIONS: &[&str] = &[
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".webp", ".ico",
];

#[pyclass]
pub struct ZipScanner {
    image_extensions: HashSet<String>,
}

#[pymethods]
impl ZipScanner {
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

    fn is_image_file(&self, filename: &str) -> bool {
        if filename.is_empty() || filename.ends_with('/') {
            return false;
        }
        let lower_name = filename.to_lowercase();
        for ext in &self.image_extensions {
            if lower_name.ends_with(ext) {
                return true;
            }
        }
        false
    }

    fn analyze_zip(
        &self,
        zip_path: &str,
    ) -> PyResult<(bool, Option<Vec<String>>, Option<f64>, Option<u64>, u32)> {
        let path = Path::new(zip_path);

        if !path.exists() {
            return Ok((false, None, None, None, 0));
        }

        let metadata = match fs::metadata(path) {
            Ok(m) => m,
            Err(_) => return Ok((false, None, None, None, 0)),
        };

        let mod_time = metadata
            .modified()
            .ok()
            .and_then(|t| {
                t.duration_since(std::time::UNIX_EPOCH)
                    .ok()
                    .map(|d| d.as_secs_f64())
            });
        let file_size = metadata.len();

        let file = match fs::File::open(path) {
            Ok(f) => f,
            Err(_) => return Ok((false, None, mod_time, Some(file_size), 0)),
        };

        let mut zip = match zip::ZipArchive::new(file) {
            Ok(z) => z,
            Err(_) => return Ok((false, None, mod_time, Some(file_size), 0)),
        };

        let mut image_members = Vec::new();
        let mut image_count = 0u32;
        let mut contains_only_images = true;
        let mut has_at_least_one_file = false;

        for i in 0..zip.len() {
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
                image_members.push(filename.to_string());
            } else {
                contains_only_images = false;
                image_members.clear();
                break;
            }
        }

        let is_valid = has_at_least_one_file && contains_only_images;
        let members = if is_valid {
            Some(image_members)
        } else {
            None
        };

        Ok((is_valid, members, mod_time, Some(file_size), image_count))
    }
}

#[pyclass]
pub struct ImageProcessor {
    // For caching during operations
}

#[pymethods]
impl ImageProcessor {
    #[new]
    fn new() -> Self {
        ImageProcessor {}
    }

    fn generate_thumbnail(
        &self,
        image_data: &[u8],
        max_width: u32,
        max_height: u32,
        fast_mode: bool,
    ) -> PyResult<Vec<u8>> {
        let img = image::load_from_memory(image_data)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyIOError, _>(e.to_string()))?;

        let (width, height) = img.dimensions();
        let aspect_ratio = width as f32 / height as f32;

        let new_height = max_height;
        let new_width = ((new_height as f32) * aspect_ratio) as u32;

        let final_width = if new_width > max_width { max_width } else { new_width };
        let final_height = (final_width as f32 / aspect_ratio) as u32;

        let img = img.thumbnail(final_width, final_height);

        let mut thumb_data = Vec::new();
        img.write_to(&mut std::io::Cursor::new(&mut thumb_data), image::ImageFormat::Png)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PyIOError, _>(e.to_string()))?;

        Ok(thumb_data)
    }

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

    fn validate_image_format(&self, image_data: &[u8]) -> PyResult<bool> {
        match image::load_from_memory(image_data) {
            Ok(_) => Ok(true),
            Err(_) => Ok(false),
        }
    }
}

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

#[pymodule]
fn arkview_core(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_class::<ZipScanner>()?;
    m.add_class::<ImageProcessor>()?;
    m.add_function(wrap_pyfunction!(format_size, m)?)?;
    Ok(())
}

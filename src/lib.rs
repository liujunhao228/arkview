use pyo3::prelude::*;
use rayon::prelude::*;
use std::collections::HashSet;
use std::fs;
use std::io::Read;
use std::path::Path;
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
        
        // Find the last dot for extension
        if let Some(dot_pos) = filename.rfind('.') {
            let ext = &filename[dot_pos..].to_lowercase();
            return self.image_extensions.contains(ext);
        }
        false
    }

    fn analyze_zip(
        &self,
        zip_path: &str,
        collect_members: Option<bool>,
    ) -> PyResult<(bool, Option<Vec<String>>, Option<f64>, Option<u64>, u32)> {
        let should_collect = collect_members.unwrap_or(true);
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

        // Check for potentially huge files to avoid hanging on extremely large archives
        if file_size > 500 * 1024 * 1024 { // 500MB limit for safety - can be adjusted
            return Ok((false, None, mod_time, Some(file_size), 0));
        }

        // For potentially problematic files, try to read just a small portion first
        let file = match fs::File::open(path) {
            Ok(f) => f,
            Err(_) => return Ok((false, None, mod_time, Some(file_size), 0)),
        };

        // Check if we can read the start of the file to verify it's accessible
        let mut buffer = [0; 4];  // Read just first 4 bytes
        let mut file_clone = file.try_clone().unwrap_or(file);
        match file_clone.read_exact(&mut buffer) {
            Ok(_) => {
                // File readable, proceed with ZIP opening
                drop(file_clone); // Close the cloned file handle
            },
            Err(_) => {
                // Can't read the file, likely corrupted or locked
                return Ok((false, None, mod_time, Some(file_size), 0));
            }
        }

        // Now try to open the ZIP - if this hangs, it's likely a Rust-side issue
        let file = match fs::File::open(path) {
            Ok(f) => f,
            Err(_) => return Ok((false, None, mod_time, Some(file_size), 0)),
        };

        let mut zip = match zip::ZipArchive::new(file) {
            Ok(z) => z,
            Err(_) => return Ok((false, None, mod_time, Some(file_size), 0)),
        };

        let total_entries = zip.len();

        // Check for potentially huge number of entries to avoid hanging
        if total_entries > 10000 {
            return Ok((false, None, mod_time, Some(file_size), 0));
        }

        let mut image_members = if should_collect {
            Vec::with_capacity(std::cmp::min(total_entries, 100))
        } else {
            Vec::new()
        };
        let mut image_count = 0u32;
        let mut has_at_least_one_file = false;

        // Start timing to prevent hanging during processing
        use std::time::Instant;
        let start_time = Instant::now();
        let max_processing_time = std::time::Duration::from_secs(15); // 15 seconds max processing time

        // Check if all files are images (early exit on first non-image)
        // Limit processing to first 1000 entries to avoid hanging on archives with many files
        let limit = std::cmp::min(total_entries, 1000);
        for i in 0..limit {
            // Check if we've exceeded our processing time limit
            if start_time.elapsed() > max_processing_time {
                println!("Processing time exceeded for {}", zip_path);
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
                // Found non-image file, archive is not valid
                return Ok((false, None, mod_time, Some(file_size), image_count));
            }
        }

        // If we reached the limit without finding non-image files,
        // check if there are more entries that weren't processed
        if limit == 1000 && total_entries > 1000 {
            return Ok((false, None, mod_time, Some(file_size), image_count));
        }

        let is_valid = has_at_least_one_file && image_count > 0;
        let members = if is_valid && should_collect {
            Some(image_members)
        } else {
            None
        };

        Ok((is_valid, members, mod_time, Some(file_size), image_count))
    }

    fn batch_analyze_zips(
        &self,
        zip_paths: Vec<String>,
        collect_members: Option<bool>,
    ) -> PyResult<Vec<(String, bool, Option<Vec<String>>, Option<f64>, Option<u64>, u32)>> {
        let should_collect = collect_members.unwrap_or(true);
        
        // Use rayon for parallel processing
        let results: Vec<(String, bool, Option<Vec<String>>, Option<f64>, Option<u64>, u32)> = zip_paths
            .into_par_iter()
            .map(|zip_path| {
                let analysis_result = self.analyze_zip(&zip_path, Some(should_collect));
                match analysis_result {
                    Ok((is_valid, members, mod_time, file_size, image_count)) => {
                        (zip_path, is_valid, members, mod_time, file_size, image_count)
                    }
                    Err(_) => {
                        (zip_path, false, None, None, None, 0)
                    }
                }
            })
            .collect();
        
        Ok(results)
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

        let img = if fast_mode {
            // 使用更快的采样算法
            img.thumbnail(final_width, final_height)
        } else {
            // 使用默认质量的采样算法
            img.resize(final_width, final_height, image::imageops::FilterType::Lanczos3)
        };

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
fn arkview_core(_py: Python, m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<ZipScanner>()?;
    m.add_class::<ImageProcessor>()?;
    m.add_function(wrap_pyfunction!(format_size, m)?)?;
    Ok(())
}

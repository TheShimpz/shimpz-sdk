//! Canonical Assistant icon validation.

use crate::SourceTreeError;

const PNG_SIGNATURE: &[u8; 8] = b"\x89PNG\r\n\x1a\n";

/// Validate the static 1024-by-1024 PNG required by source-package v1.
///
/// # Errors
///
/// Returns `invalid_icon` for malformed PNG structure or dimensions and
/// `animated_icon` when the PNG carries an animation control chunk.
pub fn validate_source_icon(contents: &[u8]) -> Result<(), SourceTreeError> {
    if !contents.starts_with(PNG_SIGNATURE) {
        return reject("invalid_icon");
    }
    let mut state = IconState::default();
    let mut offset = PNG_SIGNATURE.len();
    while offset < contents.len() {
        let length = read_u32(contents, offset).ok_or_else(invalid)? as usize;
        let kind_start = offset.checked_add(4).ok_or_else(invalid)?;
        let data_start = kind_start.checked_add(4).ok_or_else(invalid)?;
        let data_end = data_start.checked_add(length).ok_or_else(invalid)?;
        let chunk_end = data_end.checked_add(4).ok_or_else(invalid)?;
        let kind = contents.get(kind_start..data_start).ok_or_else(invalid)?;
        let data = contents.get(data_start..data_end).ok_or_else(invalid)?;
        let expected_crc = read_u32(contents, data_end).ok_or_else(invalid)?;
        if !kind.iter().all(u8::is_ascii_alphabetic) || crc32(kind, data) != expected_crc {
            return reject("invalid_icon");
        }
        state.accept(kind, data, chunk_end == contents.len())?;
        offset = chunk_end;
    }
    state.finish()
}

#[derive(Default)]
struct IconState {
    color_type: Option<u8>,
    saw_idat: bool,
    saw_iend: bool,
    saw_plte: bool,
}

impl IconState {
    fn accept(
        &mut self,
        kind: &[u8],
        data: &[u8],
        final_chunk: bool,
    ) -> Result<(), SourceTreeError> {
        match kind {
            b"IHDR" if self.color_type.is_none() && !self.saw_idat => {
                self.color_type = Some(validate_ihdr(data)?);
            }
            b"acTL" => return reject("animated_icon"),
            b"PLTE" if !self.saw_idat => self.saw_plte = true,
            b"IDAT" if self.color_type.is_some() && !self.saw_iend => self.saw_idat = true,
            b"IEND" if data.is_empty() && self.saw_idat && final_chunk => self.saw_iend = true,
            b"IHDR" | b"IEND" => return reject("invalid_icon"),
            _ if self.saw_iend => return reject("invalid_icon"),
            _ => {}
        }
        Ok(())
    }

    fn finish(self) -> Result<(), SourceTreeError> {
        if !self.saw_iend || self.color_type == Some(3) && !self.saw_plte {
            return reject("invalid_icon");
        }
        Ok(())
    }
}

fn validate_ihdr(data: &[u8]) -> Result<u8, SourceTreeError> {
    if data.len() != 13 {
        return reject("invalid_icon");
    }
    let width = read_u32(data, 0).ok_or_else(invalid)?;
    let height = read_u32(data, 4).ok_or_else(invalid)?;
    let depth = data[8];
    let color_type = data[9];
    if width != 1024
        || height != 1024
        || !valid_depth(color_type, depth)
        || data[10] != 0
        || data[11] != 0
        || data[12] > 1
    {
        return reject("invalid_icon");
    }
    Ok(color_type)
}

const fn valid_depth(color_type: u8, depth: u8) -> bool {
    match color_type {
        0 => matches!(depth, 1 | 2 | 4 | 8 | 16),
        2 | 4 | 6 => matches!(depth, 8 | 16),
        3 => matches!(depth, 1 | 2 | 4 | 8),
        _ => false,
    }
}

fn read_u32(contents: &[u8], offset: usize) -> Option<u32> {
    contents
        .get(offset..offset.checked_add(4)?)?
        .try_into()
        .ok()
        .map(u32::from_be_bytes)
}

fn crc32(kind: &[u8], data: &[u8]) -> u32 {
    let mut crc = u32::MAX;
    for byte in kind.iter().chain(data) {
        crc ^= u32::from(*byte);
        for _ in 0..8 {
            crc = (crc >> 1) ^ (0xedb8_8320 & 0_u32.wrapping_sub(crc & 1));
        }
    }
    !crc
}

const fn invalid() -> SourceTreeError {
    SourceTreeError::new("invalid_icon")
}

const fn reject<T>(code: &'static str) -> Result<T, SourceTreeError> {
    Err(SourceTreeError::new(code))
}

# Norynth File Organizer

Automated file organization with smart date detection and keyword-based classification.

## Features

- **Smart Date Detection** - Extracts dates from filenames (15+ formats) and EXIF data
- **Keyword Classification** - Analyzes file content (PDF, DOCX, text) for automatic categorization
- **Batch Processing** - Organize thousands of files with progress tracking
- **Undo History** - One-click rollback of any organization operation
- **100% Local** - No cloud, no API keys, complete privacy
- **Duplicate Detection** - MD5-based duplicate identification

## Installation

```bash
# Windows
run.bat

# Or from source
pip install -r requirements.txt
python file_organizer.py
```

## Usage

1. Launch the application
2. Add files or folders to organize
3. Choose organization strategy:
   - **By Type** - Images, Documents, Videos, etc.
   - **By Date** - File modification date
   - **By Extracted Date** - Date from filename/EXIF
   - **By Content** - Keyword-based classification
   - **By Size** - Small/Medium/Large/Very Large
4. Enable "Smart Rename" for date-prefixed filenames
5. Click "ORGANIZE FILES"

## Requirements

- Python 3.8+
- PyMuPDF (PDF support)
- python-docx (DOCX support)
- Pillow (image support)
- piexif (EXIF support)

## License

Proprietary - Norynth Technologies

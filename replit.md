# iOS App Signer

## Overview

This is a Flask-based web application that provides iOS app signing capabilities. The service allows users to upload .ipa files along with their iOS development certificates (.p12) and provisioning profiles (.mobileprovision) to create signed iOS applications. The application also generates manifest files for over-the-air (OTA) installation of signed apps directly to iOS devices.

## User Preferences

Preferred communication style: Simple, everyday language.

## Recent Changes

**Date: 2025-08-07**
- Fixed SystemExit(1) timeout error (the "samer error") by:
  - Created gunicorn.conf.py with proper timeout settings (600s for large file uploads)
  - Added better error handling for file uploads and request processing
  - Improved temporary file cleanup with try/finally blocks
  - Added specific error handlers for file size limits (413) and internal errors (500)
- Enhanced file upload processing with better validation and error messages
- Added timeout protection for large IPA file processing
- Successfully installed working zsign binary (v0.7) for iOS app signing
- Fixed OTA installation HTTPS certificate issue by prioritizing transfer.sh URLs for manifest serving
- Modified app to provide OTA-only functionality, removing direct download options  
- Changed from transfer.sh dependency to local serving for complete independence
- App generates local manifest and IPA URLs with HTTPS for OTA installation compatibility
- Platform-agnostic design works on Railway, Replit, or any deployment platform with automatic URL detection
- Successfully tested OTA installation process - apps install correctly with expected integrity warnings for non-App Store certificates

## System Architecture

### Frontend Architecture
- **Technology**: HTML templates with Bootstrap CSS framework and Font Awesome icons
- **Design Pattern**: Server-side rendered templates using Flask's Jinja2 templating engine
- **UI Components**: Single-page form interface for file uploads (IPA, P12 certificate, provisioning profile) and password input
- **Styling**: Dark theme Bootstrap with responsive design for mobile and desktop compatibility

### Backend Architecture
- **Framework**: Flask web framework with Python
- **File Handling**: Multi-part form data processing for large file uploads (up to 1GB)
- **Temporary Storage**: Uses system temporary directories for processing uploaded files
- **Process Management**: Subprocess execution for external signing tools
- **Security**: File type validation and secure temporary file handling

### Core Components
- **IPA Processing**: Extracts and analyzes iOS app bundles using zipfile and plistlib
- **Signing Service**: Integrates with zsign executable for iOS app code signing
- **Manifest Generation**: Creates iOS-compatible manifest.plist files for OTA deployment
- **Bundle Analysis**: Extracts app metadata including bundle ID and display name from Info.plist

### File Processing Workflow
1. **Upload Validation**: Accepts .ipa, .p12, and .mobileprovision file types
2. **Temporary Extraction**: Unzips IPA files to analyze app structure and metadata
3. **Signing Process**: Executes zsign with provided certificate and provisioning profile
4. **Manifest Creation**: Generates XML manifest for iOS OTA installation
5. **Cleanup**: Automatic temporary file cleanup after processing

### Security Considerations
- **File Size Limits**: 1GB maximum upload size to prevent resource exhaustion
- **Temporary File Management**: Secure handling and cleanup of sensitive certificate files
- **Process Isolation**: External signing tool execution in controlled environment

## External Dependencies

### Third-Party Tools
- **zsign**: External executable for iOS app code signing (must be present in application root)

### Python Libraries
- **Flask**: Web framework for handling HTTP requests and responses
- **requests**: HTTP client library for external API communication
- **zipfile**: Built-in library for IPA file extraction and manipulation
- **plistlib**: Built-in library for parsing iOS property list files
- **subprocess**: Built-in library for executing external signing tools
- **tempfile**: Built-in library for secure temporary file management

### Frontend Dependencies
- **Bootstrap**: CSS framework served via CDN for responsive UI design
- **Font Awesome**: Icon library served via CDN for UI enhancement

### System Requirements
- **File System**: Write access to /tmp directory for temporary file processing
- **Executable Permissions**: zsign binary must have executable permissions (755)
- **Python Environment**: Compatible with Python 3.x standard library modules
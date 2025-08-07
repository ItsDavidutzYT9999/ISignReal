import os
import subprocess
import tempfile
import zipfile
import plistlib
import requests
import logging
import time
import shutil
import signal
from flask import Flask, request, jsonify, render_template, send_file, abort
from werkzeug.exceptions import RequestEntityTooLarge

# Set up logging
logging.basicConfig(level=logging.DEBUG)

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 1024 * 1024 * 1024  # 1GB limit
app.config['UPLOAD_FOLDER'] = '/tmp'
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 300  # 5 minutes cache for downloads
app.secret_key = os.environ.get("SESSION_SECRET", "dev-secret-key")

ZSIGN_PATH = './zsign'  # path to zsign executable

# Ensure zsign has executable permissions on startup
if os.path.exists(ZSIGN_PATH):
    os.chmod(ZSIGN_PATH, 0o755)

# Timeout handler for subprocess calls
def timeout_handler(signum, frame):
    raise TimeoutError("Operation timed out")

@app.errorhandler(413)
@app.errorhandler(RequestEntityTooLarge)
def handle_file_too_large(e):
    app.logger.error("File upload too large")
    return jsonify({'error': 'File too large. Maximum allowed size is 1GB.'}), 413

@app.errorhandler(500)
def handle_internal_error(e):
    app.logger.error(f"Internal server error: {str(e)}")
    return jsonify({'error': 'Internal server error occurred. Please try again with a smaller file or contact support.'}), 500

def extract_bundle_and_name(ipa_path):
    """Extract bundle ID and app name from IPA file"""
    with tempfile.TemporaryDirectory() as tmpdir:
        with zipfile.ZipFile(ipa_path, 'r') as zip_ref:
            zip_ref.extractall(tmpdir)

        payload_path = os.path.join(tmpdir, 'Payload')
        apps = [d for d in os.listdir(payload_path) if d.endswith('.app')]
        if not apps:
            raise Exception("No .app folder found in Payload")

        app_path = os.path.join(payload_path, apps[0])
        info_plist_path = os.path.join(app_path, 'Info.plist')

        with open(info_plist_path, 'rb') as f:
            plist = plistlib.load(f)

        bundle_id = plist.get('CFBundleIdentifier')
        app_name = plist.get('CFBundleDisplayName') or plist.get('CFBundleName') or "UnknownApp"
        return bundle_id, app_name

def generate_manifest(bundle_id, app_name, ipa_url):
    """Generate iOS manifest.plist for OTA installation"""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>items</key>
  <array>
    <dict>
      <key>assets</key>
      <array>
        <dict>
          <key>kind</key>
          <string>software-package</string>
          <key>url</key>
          <string>{ipa_url}</string>
        </dict>
      </array>
      <key>metadata</key>
      <dict>
        <key>bundle-identifier</key>
        <string>{bundle_id}</string>
        <key>bundle-version</key>
        <string>1.0</string>
        <key>kind</key>
        <string>software</string>
        <key>title</key>
        <string>{app_name}</string>
      </dict>
    </dict>
  </array>
</dict>
</plist>"""

def upload_to_transfersh(file_path, filename=None):
    """Upload file to transfer.sh and return download URL"""
    try:
        file_size = os.path.getsize(file_path)
        app.logger.debug(f"Uploading file {file_path} ({file_size} bytes) to transfer.sh")
        
        # Use filename from path if not provided
        if not filename:
            filename = os.path.basename(file_path)
        
        # Increase timeout for large files
        timeout = 300 if file_size > 100 * 1024 * 1024 else 120  # 5 min for files > 100MB
        
        with open(file_path, 'rb') as f:
            # Transfer.sh expects the filename in the URL path
            upload_url = f'https://transfer.sh/{filename}'
            headers = {'Content-Type': 'application/octet-stream'}
            
            response = requests.put(upload_url, data=f, headers=headers, timeout=timeout)
            
            # Check if response is successful
            if response.status_code != 200:
                app.logger.error(f"Transfer.sh upload failed with status {response.status_code}: {response.text}")
                return None, f"Upload service returned error {response.status_code}"
            
            # Transfer.sh returns the download URL directly in the response text
            download_url = response.text.strip()
            
            app.logger.debug(f"Transfer.sh upload successful: {download_url}")
            return download_url, None
            
    except requests.exceptions.RequestException as e:
        app.logger.error(f"Network error during upload: {str(e)}")
        return None, f"Network error: {str(e)}"
    except Exception as e:
        app.logger.error(f"Unexpected error during upload: {str(e)}")
        return None, f"Upload error: {str(e)}"

@app.route('/')
def index():
    """Render the main page with upload form"""
    return render_template('index.html')

@app.route('/test')
def test_page():
    """Simple test endpoint for debugging"""
    return jsonify({
        'status': 'ok',
        'message': 'iOS App Signer is running',
        'zsign_available': os.path.exists(ZSIGN_PATH)
    })

@app.route('/download/<filename>')
def download_file(filename):
    """Download signed IPA files or manifest files"""
    try:
        file_path = os.path.join('/tmp', filename)
        if not os.path.exists(file_path):
            app.logger.error(f"File not found: {file_path}")
            abort(404)
        
        if filename.endswith('.plist'):
            # Serve manifest files with correct MIME type for iOS
            app.logger.debug(f"Serving manifest file: {file_path}")
            return send_file(file_path, as_attachment=False, mimetype='text/xml', download_name=filename)
        elif filename.endswith('.ipa'):
            app.logger.debug(f"Serving IPA file: {file_path}")
            return send_file(file_path, as_attachment=True, download_name=filename)
        else:
            app.logger.error(f"Invalid file type requested: {filename}")
            abort(400)
            
    except Exception as e:
        app.logger.error(f"Download error: {str(e)}")
        abort(500)

@app.route('/sign', methods=['POST'])
def sign_ipa():
    """Main endpoint for signing IPA files"""
    app.logger.debug("Received sign request")
    tmpdir_path = None
    try:
        # Check if request has file data
        if not request.files:
            return jsonify({'error': 'No files uploaded'}), 400
            
        # Get uploaded files and form data with better error handling
        ipa = request.files.get('ipa')
        p12 = request.files.get('p12')
        provision = request.files.get('provision')
        password = request.form.get('password')

        # Validate required fields
        if not all([ipa, p12, provision, password]):
            return jsonify({'error': 'Missing one or more required fields'}), 400
        
        # Check if files have content and proper filenames
        if not ipa or not ipa.filename or ipa.filename == '':
            return jsonify({'error': 'No IPA file selected'}), 400
        if not p12 or not p12.filename or p12.filename == '':
            return jsonify({'error': 'No P12 certificate selected'}), 400
        if not provision or not provision.filename or provision.filename == '':
            return jsonify({'error': 'No provisioning profile selected'}), 400
            
        # Validate file types
        if not ipa.filename.endswith('.ipa'):
            return jsonify({'error': 'IPA file must have .ipa extension'}), 400
        if not p12.filename.endswith('.p12'):
            return jsonify({'error': 'Certificate must have .p12 extension'}), 400
        if not provision.filename.endswith('.mobileprovision'):
            return jsonify({'error': 'Provisioning profile must have .mobileprovision extension'}), 400

        # Create temporary directory with explicit cleanup
        tmpdir_path = tempfile.mkdtemp(prefix='ios_signer_')
        app.logger.debug(f"Created temporary directory: {tmpdir_path}")
        
        try:
            # Save uploaded files with error handling
            ipa_path = os.path.join(tmpdir_path, 'input.ipa')
            p12_path = os.path.join(tmpdir_path, 'cert.p12')
            provision_path = os.path.join(tmpdir_path, 'profile.mobileprovision')
            output_path = os.path.join(tmpdir_path, 'signed.ipa')
            manifest_path = os.path.join(tmpdir_path, 'manifest.plist')

            app.logger.debug("Saving uploaded files...")
            try:
                ipa.save(ipa_path)
                p12.save(p12_path)
                provision.save(provision_path)
                app.logger.debug("Files saved successfully")
            except Exception as save_error:
                app.logger.error(f"Failed to save uploaded files: {str(save_error)}")
                return jsonify({'error': 'Failed to save uploaded files', 'details': str(save_error)}), 500

            # Extract bundle info from the IPA
            try:
                bundle_id, app_name = extract_bundle_and_name(ipa_path)
                app.logger.debug(f"Extracted app info: {app_name} ({bundle_id})")
            except Exception as e:
                return jsonify({'error': 'Failed to extract bundle id and app name', 'details': str(e)}), 500

            # Run zsign to sign the IPA
            cmd = [
                ZSIGN_PATH,
                '-k', p12_path,
                '-p', password,
                '-m', provision_path,
                '-o', output_path,
                ipa_path
            ]

            app.logger.debug(f"Running zsign command: {' '.join(cmd[:-1])} [password hidden] {cmd[-1]}")
            try:
                result = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)
                app.logger.debug(f"zsign output: {result}")
            except subprocess.CalledProcessError as e:
                app.logger.error(f"zsign failed with exit code {e.returncode}: {e.output}")
                error_msg = e.output if isinstance(e.output, str) else e.output.decode() if e.output else "Unknown zsign error"
                return jsonify({'error': 'Signing failed', 'details': error_msg}), 500

            # Save signed IPA to a permanent location for direct download
            signed_filename = f"signed_{bundle_id}_{int(time.time())}.ipa"
            permanent_path = os.path.join('/tmp', signed_filename)
            
            # Copy the signed IPA to permanent location
            shutil.copy2(output_path, permanent_path)
            app.logger.debug(f"Signed IPA saved to: {permanent_path}")
            
            # Check file size
            file_size_mb = round(os.path.getsize(permanent_path) / (1024*1024), 2)
            app.logger.debug(f"Signed IPA size: {file_size_mb} MB")
            
            # Save manifest to permanent location for local serving
            manifest_filename = f"manifest_{bundle_id}_{int(time.time())}.plist"
            permanent_manifest_path = os.path.join('/tmp', manifest_filename)
            
            # Generate manifest and URLs for local OTA installation
            # Use HTTPS URLs that will work when deployed on Replit
            base_url = request.url_root
            if base_url.startswith('http://'):
                # Replace with HTTPS for OTA compatibility
                base_url = base_url.replace('http://', 'https://')
            
            direct_ipa_url = f"{base_url}download/{signed_filename}"
            local_manifest_url = f"{base_url}download/{manifest_filename}"
            
            app.logger.debug(f"Using local URLs for OTA - Base URL: {base_url}")
            
            # Generate manifest with local URLs
            manifest_content = generate_manifest(bundle_id, app_name, direct_ipa_url)
            with open(permanent_manifest_path, 'w', encoding='utf-8') as f:
                f.write(manifest_content)
            
            # Create ITMS services URL pointing to local manifest
            itms_services_url = f"itms-services://?action=download-manifest&url={local_manifest_url}"
            
            app.logger.debug(f"Local OTA URLs - IPA: {direct_ipa_url}, Manifest: {local_manifest_url}")
            app.logger.debug(f"ITMS services URL: {itms_services_url}")
            
            # Return OTA installation info
            return jsonify({
                'success': True,
                'message': 'App signed successfully! Use the OTA link to install on your iOS device.',
                'itms_services_url': itms_services_url,
                'manifest_url': local_manifest_url,
                'ipa_url': direct_ipa_url,
                'app_info': {
                    'name': app_name,
                    'bundle_id': bundle_id,
                    'size_mb': file_size_mb
                },
                'note': 'OTA installation works locally. For production use, deploy this app to get valid HTTPS certificates.'
            })
            
        finally:
            # Clean up temporary directory
            if tmpdir_path and os.path.exists(tmpdir_path):
                try:
                    shutil.rmtree(tmpdir_path)
                    app.logger.debug(f"Cleaned up temporary directory: {tmpdir_path}")
                except Exception as cleanup_error:
                    app.logger.warning(f"Failed to cleanup temporary directory: {cleanup_error}")
    
    except Exception as e:
        app.logger.error(f"Unexpected error in sign_ipa: {str(e)}")
        # Clean up temporary directory in case of error
        if tmpdir_path and os.path.exists(tmpdir_path):
            try:
                shutil.rmtree(tmpdir_path)
                app.logger.debug(f"Cleaned up temporary directory after error: {tmpdir_path}")
            except Exception as cleanup_error:
                app.logger.warning(f"Failed to cleanup temporary directory after error: {cleanup_error}")
        return jsonify({'error': 'Unexpected error occurred', 'details': str(e)}), 500

if __name__ == '__main__':
    # Ensure zsign has executable permissions
    if os.path.exists(ZSIGN_PATH):
        os.chmod(ZSIGN_PATH, 0o755)
    
    app.run(host='0.0.0.0', port=5000, debug=True)

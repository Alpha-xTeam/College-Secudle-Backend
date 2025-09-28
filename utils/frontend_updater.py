import os
import re
from utils.network_utils import get_server_url

def update_frontend_api_files():
    """
    Update frontend API files with new IP
    """
    frontend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'frontend', 'src', 'api')
    
    if not os.path.exists(frontend_dir):
        print("Frontend API directory not found")
        return False
    
    new_url = get_server_url()
    updated_files = []
    
    # List of API files that need updating
    api_files = [
        'auth.js',
        'rooms.js', 
        'schedules.js'
    ]
    
    for filename in api_files:
        file_path = os.path.join(frontend_dir, filename)
        if os.path.exists(file_path):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Replace any form of API_URL declaration with env-or-literal form
                decl_pattern = r"const\s+API_URL\s*=.*?;"
                match_decl = re.search(decl_pattern, content, re.DOTALL)
                if match_decl:
                    new_decl = f"const API_URL = process.env.REACT_APP_API_URL || '{new_url}';"
                    new_content = content[:match_decl.start()] + new_decl + content[match_decl.end():]
                    with open(file_path, 'w', encoding='utf-8') as f:
                        f.write(new_content)
                    updated_files.append(filename)
                    print(f"Updated {filename}")
                else:
                    print(f"API_URL not found in {filename}")
                    
            except Exception as e:
                print(f"Error updating {filename}: {str(e)}")
    
    return len(updated_files) > 0

def get_frontend_api_status():
    """
    Get frontend API files status
    """
    frontend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'frontend', 'src', 'api')
    
    if not os.path.exists(frontend_dir):
        return {'status': 'error', 'message': 'API directory not found'}
    
    current_url = get_server_url()
    status = {
        'status': 'ok',
        'current_url': current_url,
        'files': []
    }
    
    api_files = ['auth.js', 'rooms.js', 'schedules.js']
    
    for filename in api_files:
        file_path = os.path.join(frontend_dir, filename)
        if os.path.exists(file_path):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Extract current URL from declaration if present
                decl_pattern = r"const\s+API_URL\s*=.*?;"
                match_decl = re.search(decl_pattern, content, re.DOTALL)
                if match_decl:
                    decl = match_decl.group(0)
                    url_match = re.search(r"['\"](http://[^'\"]+)['\"]", decl)
                    file_url = url_match.group(1) if url_match else 'Dynamic/Env'
                    status['files'].append({
                        'filename': filename,
                        'url': file_url,
                        'needs_update': file_url != 'Dynamic/Env' and file_url != current_url
                    })
                else:
                    status['files'].append({
                        'filename': filename,
                        'url': 'Not specified',
                        'needs_update': True
                    })
                    
            except Exception as e:
                status['files'].append({
                    'filename': filename,
                    'url': 'Read error',
                    'needs_update': True,
                    'error': str(e)
                })
    
    return status

def auto_update_frontend():
    """
    Auto-update frontend when server starts
    """
    print("Updating frontend API files...")
    
    if update_frontend_api_files():
        print("Successfully updated all API files")
    else:
        print("No API files were updated")
    
    # Show files status
    status = get_frontend_api_status()
    print(f"Current URL: {status['current_url']}")
    
    for file_info in status['files']:
        status_icon = "✅" if not file_info['needs_update'] else "⚠️"
        print(f"{file_info['filename']}: {file_info['url']}") 
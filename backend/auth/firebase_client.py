import firebase_admin
from firebase_admin import credentials, auth
import os

def init_firebase():
    """Initialize the Firebase Admin SDK using the serviceAccountKey.json"""
    # Check multiple possible paths for the service account key
    local_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "serviceAccountKey.json")
    render_secret_path = "/etc/secrets/serviceAccountKey.json"
    
    # Priority: env var > Render secret files > local project file
    candidate_paths = []
    env_path = os.getenv("FIREBASE_CREDENTIALS")
    if env_path:
        candidate_paths.append(env_path)
    candidate_paths.append(render_secret_path)
    candidate_paths.append(local_path)
    
    if not firebase_admin._apps:
        cred_file = None
        for path in candidate_paths:
            if os.path.exists(path):
                cred_file = path
                break
        
        if cred_file:
            cred = credentials.Certificate(cred_file)
            firebase_admin.initialize_app(cred)
            print(f"✅ Firebase Admin SDK initialized successfully (from {cred_file}).")
        else:
            print(f"⚠️ Warning: Firebase credentials not found in any of:")
            for path in candidate_paths:
                print(f"   - {path}")
            print("Authentication will fail until serviceAccountKey.json is provided.")

def verify_token(id_token: str) -> dict:
    """Verify a Firebase ID token and return the decoded payload."""
    try:
        decoded_token = auth.verify_id_token(id_token)
        return decoded_token
    except Exception as e:
        raise ValueError(f"Invalid Firebase ID token: {str(e)}")

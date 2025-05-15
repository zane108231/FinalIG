import os
import requests
import time
import base64
import json
import logging
import random
from datetime import datetime, timedelta
from flask import Flask, jsonify, request, render_template, flash, send_file
from dotenv import load_dotenv
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from TikTokApi import TikTokApi
from functools import wraps

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-key")

# Cache for uptime checks
uptime_cache = {
    'last_check': None,
    'status': 'online',
    'requests_served': 0
}

# Cookie management
class CookieManager:
    def __init__(self):
        self.cookies = []
        self.current_index = 0
        self.last_rotation = datetime.now()
        self.rotation_interval = timedelta(minutes=30)  # Rotate every 30 minutes
        self.load_cookies()
        logger.info(f"CookieManager initialized with {len(self.cookies)} cookies")

    def load_cookies(self):
        # Load cookies from environment variables
        cookie_str = os.getenv("INSTAGRAM_COOKIES", "")
        if cookie_str:
            self.cookies = [cookie.strip() for cookie in cookie_str.split("||")]
            logger.info(f"Loaded {len(self.cookies)} cookies from environment")
        if not self.cookies:
            logger.warning("No Instagram cookies found in environment variables")

    def get_current_cookie(self):
        current_time = datetime.now()
        if current_time - self.last_rotation > self.rotation_interval:
            logger.info("Rotation interval reached, rotating cookie")
            self.rotate_cookie()
        current_cookie = self.cookies[self.current_index] if self.cookies else ""
        logger.info(f"Using cookie index {self.current_index} (Total cookies: {len(self.cookies)})")
        return current_cookie

    def rotate_cookie(self):
        if len(self.cookies) > 1:
            old_index = self.current_index
            self.current_index = (self.current_index + 1) % len(self.cookies)
            self.last_rotation = datetime.now()
            logger.info(f"Rotated cookie: {old_index} -> {self.current_index} (Total cookies: {len(self.cookies)})")
        else:
            logger.warning("Cannot rotate cookie: only one cookie available")

    def add_cookie(self, cookie):
        if cookie and cookie not in self.cookies:
            self.cookies.append(cookie)
            logger.info(f"Added new cookie. Total cookies now: {len(self.cookies)}")

cookie_manager = CookieManager()

# Rate limiting configuration - modified to exclude uptime checks
def limit_exempt_uptime():
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if request.path == '/uptime':
                return f(*args, **kwargs)
            return limiter.limit("5 per minute")(f)(*args, **kwargs)
        return wrapped
    return decorator

limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["100 per day", "20 per hour"],
    storage_uri="memory://",
    strategy="fixed-window"  # More predictable for uptime checks
)

def get_instagram_headers():
    cookie = cookie_manager.get_current_cookie()
    return {
        "User-Agent": os.getenv("INSTAGRAM_USER_AGENT", "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1"),
        "Cookie": cookie,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://www.instagram.com/",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
        "X-IG-App-ID": "936619743392459",
        "X-Requested-With": "XMLHttpRequest"
    }

def handle_instagram_response(response):
    """Handle Instagram API responses and check for rate limiting/challenges"""
    try:
        # Check for JSON decode errors first
        if response.status_code == 200:
            try:
                response.json()
            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON response (Status: {response.status_code}), likely invalid cookie")
                logger.debug(f"Response content: {response.text[:200]}...")  # Log first 200 chars of response
                cookie_manager.rotate_cookie()
                return False, "Invalid cookie or session expired"
        
        # Check for rate limiting
        if response.status_code == 429:
            logger.warning(f"Rate limit hit (Status: {response.status_code})")
            cookie_manager.rotate_cookie()
            return False, "Rate limit exceeded"
        
        # Check for access denied
        if response.status_code == 403:
            logger.warning(f"Access forbidden (Status: {response.status_code})")
            cookie_manager.rotate_cookie()
            return False, "Access forbidden"
        
        # Check for login required
        if response.status_code == 401:
            logger.warning(f"Authentication required (Status: {response.status_code})")
            cookie_manager.rotate_cookie()
            return False, "Authentication required"
        
        # Check response content for challenge indicators
        try:
            response_text = response.text.lower()
            challenge_indicators = [
                "challenge_required",
                "login_required",
                "checkpoint_required",
                "verify_phone_number",
                "verify_email",
                "suspicious_activity",
                "temporarily_blocked"
            ]
            found_indicators = [ind for ind in challenge_indicators if ind in response_text]
            if found_indicators:
                logger.warning(f"Challenge detected in response: {', '.join(found_indicators)}")
                logger.debug(f"Response content: {response_text[:200]}...")  # Log first 200 chars
                cookie_manager.rotate_cookie()
                return False, f"Challenge required: {', '.join(found_indicators)}"
        except Exception as e:
            logger.error(f"Error checking response content: {str(e)}")
        
        return True, response
        
    except Exception as e:
        logger.error(f"Error handling response: {str(e)}")
        cookie_manager.rotate_cookie()
        return False, str(e)

def make_instagram_request(url, method="GET", **kwargs):
    """Make a request to Instagram with retry logic and rate limiting"""
    max_retries = 3
    base_delay = 2
    
    for attempt in range(max_retries):
        try:
            # Add random delay between requests
            delay = base_delay + random.uniform(0, 2)
            logger.debug(f"Request attempt {attempt + 1}/{max_retries} - Waiting {delay:.2f}s")
            time.sleep(delay)
            
            current_cookie = cookie_manager.get_current_cookie()
            headers = get_instagram_headers()
            logger.debug(f"Making request to {url} with cookie index {cookie_manager.current_index}")
            
            response = requests.request(
                method,
                url,
                headers=headers,
                timeout=15,
                **kwargs
            )
            
            logger.debug(f"Response status: {response.status_code}")
            success, result = handle_instagram_response(response)
            
            if success:
                logger.debug("Request successful")
                return result
            
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                logger.warning(f"Request failed, retrying in {delay}s. Error: {result}")
                time.sleep(delay)
                continue
            
            logger.error(f"All retry attempts failed. Last error: {result}")
            return result
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed: {str(e)}")
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                logger.warning(f"Retrying in {delay}s")
                time.sleep(delay)
                continue
            raise

def process_media_item(media, media_type, is_carousel=False, carousel_index=None):
    """Process a single media item (image or video) and return its data"""
    try:
        if media_type == 1:  # Image
            image_versions = media.get("image_versions2", {}) or {}
            candidates = image_versions.get("candidates", []) or []
            if candidates and isinstance(candidates, list) and len(candidates) > 0:
                image_url = candidates[0].get("url")
                if image_url:
                    media_data = {
                        "type": "image",
                        "url": image_url
                    }
                    if is_carousel:
                        media_data.update({
                            "is_carousel_item": True,
                            "carousel_index": carousel_index
                        })
                    return media_data
                    
        elif media_type == 2:  # Video
            video_versions = media.get("video_versions", []) or []
            if video_versions and isinstance(video_versions, list) and len(video_versions) > 0:
                video_url = video_versions[0].get("url")
                if video_url:
                    # Get cover image if available
                    cover_url = None
                    image_versions = media.get("image_versions2", {}) or {}
                    candidates = image_versions.get("candidates", []) or []
                    if candidates and isinstance(candidates, list) and len(candidates) > 0:
                        cover_url = candidates[0].get("url")
                    
                    media_data = {
                        "type": "video",
                        "url": video_url,
                        "cover_url": cover_url
                    }
                    if is_carousel:
                        media_data.update({
                            "is_carousel_item": True,
                            "carousel_index": carousel_index
                        })
                    return media_data
    except Exception as e:
        raise Exception(f"Failed to process media: {str(e)}")
    return None

def process_carousel_media(carousel_media, debug_info):
    """Process carousel media items and return a list of media data"""
    media_items = []
    if not carousel_media or not isinstance(carousel_media, list):
        return media_items
        
    for idx, media in enumerate(carousel_media):
        try:
            carousel_media_type = media.get("media_type")
            media_data = process_media_item(media, carousel_media_type, True, idx)
            if media_data:
                media_items.append(media_data)
        except Exception as e:
            debug_info["errors"].append(f"Failed to process carousel item {idx}: {str(e)}")
            continue
    return media_items

def create_post_info(post, debug_info):
    """Create a post information dictionary with all necessary data"""
    try:
        # Safely get post data with defaults
        caption = post.get("caption", {}) or {}
        caption_text = caption.get("text", "") if isinstance(caption, dict) else ""
        
        post_info = {
            "id": post.get("id", ""),
            "caption": caption_text,
            "timestamp": post.get("taken_at", 0),
            "like_count": post.get("like_count", 0),
            "comment_count": post.get("comment_count", 0),
            "is_video": post.get("media_type") == 2,
            "is_carousel": post.get("media_type") == 8,
            "media": []
        }
        
        # Process media based on type
        media_type = post.get("media_type")
        
        if media_type == 1 or media_type == 2:  # Single image or video
            media_data = process_media_item(post, media_type)
            if media_data:
                post_info["media"].append(media_data)
                
        elif media_type == 8:  # Carousel
            carousel_media = post.get("carousel_media", []) or []
            post_info["media"].extend(process_carousel_media(carousel_media, debug_info))
            
        return post_info
    except Exception as e:
        raise Exception(f"Failed to create post info: {str(e)}")

def fetch_user_posts(user_id, debug_info):
    """Fetch and process all posts for a user"""
    posts_url = f"https://www.instagram.com/api/v1/feed/user/{user_id}/?count=50"
    post_items = []
    has_more_posts = True
    max_id = None
    max_posts = 100  # Set a reasonable limit to avoid too many requests
    
    while has_more_posts and len(post_items) < max_posts:
        try:
            current_url = posts_url
            if max_id:
                current_url += f"&max_id={max_id}"
            
            debug_info["stats"]["api_calls"] += 1
            posts_res = requests.get(current_url, headers=get_instagram_headers(), timeout=15)
            posts_data = posts_res.json()
            
            if not posts_data.get("items"):
                break
                
            for post in posts_data.get("items", []):
                try:
                    debug_info["stats"]["posts_processed"] += 1
                    post_info = create_post_info(post, debug_info)
                    
                    if post_info["media"]:
                        post_items.append(post_info)
                    else:
                        debug_info["warnings"].append(f"Post {post.get('id', 'unknown')} has no valid media")
                        
                except Exception as e:
                    debug_info["stats"]["posts_failed"] += 1
                    debug_info["errors"].append(f"Failed to process post {post.get('id', 'unknown')}: {str(e)}")
                    continue
            
            # Check if there are more posts to fetch
            has_more_posts = posts_data.get("more_available", False)
            max_id = posts_data.get("next_max_id")
            
            # Add a small delay between pagination requests to avoid rate limiting
            if has_more_posts and max_id:
                time.sleep(1)
                
        except Exception as e:
            debug_info["errors"].append(f"Failed to fetch posts page: {str(e)}")
            break
            
    return {"count": len(post_items), "items": post_items}

@app.route('/api/instagram/<username>')
@limit_exempt_uptime()
def api_instagram(username):
    username = username.strip()
    if not username:
        return jsonify({"error": "Missing username"}), 400
    
    # Initialize debug info
    debug_info = {
        "request_time": datetime.now().isoformat(),
        "errors": [],
        "warnings": [],
        "stats": {
            "posts_processed": 0,
            "posts_failed": 0,
            "stories_processed": 0,
            "stories_failed": 0,
            "api_calls": 0,
            "processing_time": 0
        }
    }
    
    start_time = time.time()
    try:
        # Get profile data
        debug_info["stats"]["api_calls"] += 1
        user_url = f"https://www.instagram.com/api/v1/users/web_profile_info/?username={username}"
        res = requests.get(user_url, headers=get_instagram_headers(), timeout=15)
        res.raise_for_status()
        user_data = res.json().get("data", {}).get("user", {})
        
        if not user_data:
            debug_info["errors"].append("User not found in Instagram response")
            return jsonify({"error": "User not found", "debug": debug_info}), 404
            
        pic_url = user_data.get("profile_pic_url_hd") or user_data.get("profile_pic_url")
        profile_data = {
            "username": user_data.get("username"),
            "full_name": user_data.get("full_name"),
            "profile_pic": pic_url,
            "bio": user_data.get("biography"),
            "followers": user_data.get("edge_followed_by", {}).get("count", 0),
            "following": user_data.get("edge_follow", {}).get("count", 0),
            "posts_count": user_data.get("edge_owner_to_timeline_media", {}).get("count", 0),
            "is_private": user_data.get("is_private", True)
        }
        
        if user_data.get("is_private") and not user_data.get("followed_by_viewer", False):
            debug_info["warnings"].append("Private account - limited data available")
            return jsonify({
                "profile": profile_data, 
                "stories": {"count": 0, "items": []}, 
                "posts": {"count": 0, "items": []},
                "debug": debug_info
            })
            
        user_id = user_data.get("id")
        if not user_id:
            debug_info["errors"].append("Could not fetch user ID from Instagram response")
            return jsonify({"error": "Could not fetch user ID", "debug": debug_info}), 500
            
        # Get stories
        debug_info["stats"]["api_calls"] += 1
        stories_url = f"https://i.instagram.com/api/v1/feed/user/{user_id}/reel_media/"
        stories_res = requests.get(stories_url, headers=get_instagram_headers(), timeout=10)
        stories = stories_res.json().get("items", [])
        
        story_items = []
        for story in stories:
            try:
                debug_info["stats"]["stories_processed"] += 1
                media_type = story.get("media_type")
                if media_type == 1:  # Image
                    candidates = story.get('image_versions2', {}).get('candidates', [])
                    if candidates:
                        image_url = candidates[0]['url']
                        story_items.append({"type": "image", "url": image_url})
                elif media_type == 2:  # Video
                    videos = story.get('video_versions', [])
                    if videos:
                        video_url = videos[0]['url']
                        story_items.append({"type": "video", "url": video_url})
            except Exception as e:
                debug_info["stats"]["stories_failed"] += 1
                debug_info["errors"].append(f"Failed to process story: {str(e)}")
                continue
                
        stories_data = {"count": len(story_items), "items": story_items}
        
        # Get posts using the new helper function
        posts_data = fetch_user_posts(user_id, debug_info)
        
        # Calculate processing time
        debug_info["stats"]["processing_time"] = round(time.time() - start_time, 2)
        
        return jsonify({
            "profile": profile_data,
            "stories": stories_data,
            "posts": posts_data,
            "debug": debug_info
        })
    except Exception as e:
        debug_info["errors"].append(f"Fatal error: {str(e)}")
        debug_info["stats"]["processing_time"] = round(time.time() - start_time, 2)
        return jsonify({"error": str(e), "debug": debug_info}), 500

@app.route("/cookies", methods=["GET", "POST"])
def cookie_management():
    if request.method == "POST":
        new_cookie = request.form.get("cookie", "").strip()
        if new_cookie:
            # Verify the cookie before adding
            headers = {
                "User-Agent": os.getenv("INSTAGRAM_USER_AGENT", "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1"),
                "Cookie": new_cookie
            }
            try:
                # Test the cookie with a simple request
                test_url = "https://www.instagram.com/api/v1/users/web_profile_info/?username=instagram"
                response = requests.get(test_url, headers=headers, timeout=10)
                if response.status_code == 200:
                    cookie_manager.add_cookie(new_cookie)
                    flash("Cookie added successfully and verified!", "success")
                else:
                    flash(f"Cookie verification failed (Status: {response.status_code})", "error")
            except Exception as e:
                flash(f"Cookie verification failed: {str(e)}", "error")
        else:
            flash("No cookie provided", "error")
    
    # Get all cookies with their status
    cookies_info = []
    for i, cookie in enumerate(cookie_manager.cookies):
        is_active = i == cookie_manager.current_index
        cookies_info.append({
            "index": i,
            "cookie": cookie,
            "is_active": is_active
        })
    
    return render_template(
        "cookies.html",
        cookie_count=len(cookie_manager.cookies),
        current_index=cookie_manager.current_index,
        cookies_info=cookies_info
    )

def get_tiktok_video_id(url):
    """
    Extract video ID from TikTok URL, handling both regular and shortened URLs.
    """
    try:
        # Handle shortened URLs (vt.tiktok.com)
        if 'vt.tiktok.com' in url:
            # Follow the redirect to get the full URL
            response = requests.head(url, allow_redirects=True)
            url = response.url
            
        # Extract video ID from the URL
        if '/video/' in url:
            video_id = url.split('/video/')[1].split('?')[0]
            return video_id
        else:
            raise ValueError("Invalid TikTok URL format")
    except Exception as e:
        raise ValueError(f"Could not extract video ID: {str(e)}")

@app.route('/api/tkdl/<path:video_url>')
@limit_exempt_uptime()
def download_tiktok(video_url):
    """
    API endpoint to download TikTok videos.
    
    Args:
        video_url (str): URL of the TikTok video to download.
    """
    try:
        # Create output directory if it doesn't exist
        output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'downloads')
        os.makedirs(output_dir, exist_ok=True)
        
        # Initialize TikTok API
        api = TikTokApi()
        
        # Get video ID from URL
        video_id = get_tiktok_video_id(video_url)
        
        # Get video data
        video_data = api.video(id=video_id).info()
        
        # Download video
        video_url = video_data['video']['downloadAddr']
        response = requests.get(video_url, stream=True)
        
        # Save video
        video_name = f"tiktok_{video_id}.mp4"
        video_path = os.path.join(output_dir, video_name)
        
        with open(video_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        
        # Return the video file
        return send_file(
            video_path,
            as_attachment=True,
            download_name=video_name,
            mimetype='video/mp4'
        )
        
    except Exception as e:
        logger.error(f"Error downloading TikTok video: {str(e)}")
        return jsonify({
            "error": str(e),
            "status": "failed"
        }), 500

@app.route('/uptime')
def uptime_check():
    """Special endpoint for uptime checks that doesn't count against rate limits"""
    uptime_cache['last_check'] = datetime.now().isoformat()
    uptime_cache['requests_served'] = uptime_cache.get('requests_served', 0) + 1
    return jsonify({
        "status": "online",
        "last_check": uptime_cache['last_check'],
        "requests_served": uptime_cache['requests_served'],
        "server_time": datetime.now().isoformat()
    }), 200

@app.route('/')
def status_page():
    """Enhanced status page with more information"""
    # Update cache if this is a fresh request
    if not uptime_cache['last_check']:
        uptime_cache['last_check'] = datetime.now().isoformat()
    
    status_html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>JihyoIG Status</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body {
                font-family: Arial, sans-serif;
                display: flex;
                justify-content: center;
                align-items: center;
                min-height: 100vh;
                margin: 0;
                background-color: #f0f2f5;
                color: #333;
            }
            .status-container {
                text-align: center;
                padding: 2rem;
                background-color: white;
                border-radius: 8px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.1);
                max-width: 600px;
                width: 90%;
            }
            .status-indicator {
                width: 20px;
                height: 20px;
                background-color: #4CAF50;
                border-radius: 50%;
                display: inline-block;
                margin-right: 10px;
                animation: pulse 2s infinite;
            }
            @keyframes pulse {
                0% { opacity: 1; }
                50% { opacity: 0.7; }
                100% { opacity: 1; }
            }
            h1 {
                color: #1a1a1a;
                margin: 0 0 1rem 0;
                font-size: 24px;
            }
            .status-info {
                text-align: left;
                margin: 1.5rem 0;
                padding: 1rem;
                background: #f8f9fa;
                border-radius: 6px;
            }
            .status-info p {
                margin: 0.5rem 0;
                font-size: 14px;
            }
            .status-info strong {
                display: inline-block;
                width: 120px;
            }
            .uptime-link {
                display: inline-block;
                margin-top: 1rem;
                padding: 0.5rem 1rem;
                background: #4CAF50;
                color: white;
                text-decoration: none;
                border-radius: 4px;
                font-size: 14px;
            }
            .uptime-link:hover {
                background: #3e8e41;
            }
        </style>
    </head>
    <body>
        <div class="status-container">
            <span class="status-indicator"></span>
            <h1>JihyoIG Service Status</h1>
            
            <div class="status-info">
                <p><strong>Current Status:</strong> <span id="status">Online</span></p>
                <p><strong>Last Check:</strong> <span id="last-check">{last_check}</span></p>
                <p><strong>Requests Served:</strong> <span id="requests-served">{requests_served}</span></p>
                <p><strong>Server Time:</strong> <span id="server-time">{server_time}</span></p>
            </div>
            
            <p>For uptime monitoring, use the dedicated endpoint below</p>
            <a href="/uptime" class="uptime-link">Uptime Check Endpoint</a>
        </div>
        
        <script>
            function updateTimestamp() {
                const now = new Date();
                document.getElementById('server-time').textContent = now.toLocaleString();
            }
            
            // Initial update
            updateTimestamp();
            
            // Update every second
            setInterval(updateTimestamp, 1000);
            
            // Update status from uptime endpoint periodically
            function checkStatus() {
                fetch('/uptime')
                    .then(response => response.json())
                    .then(data => {
                        document.getElementById('last-check').textContent = data.last_check;
                        document.getElementById('requests-served').textContent = data.requests_served;
                    })
                    .catch(error => {
                        console.error('Status check failed:', error);
                    });
            }
            
            // Check every 30 seconds
            setInterval(checkStatus, 30000);
            checkStatus(); // Initial check
        </script>
    </body>
    </html>
    """.format(
        last_check=uptime_cache['last_check'],
        requests_served=uptime_cache.get('requests_served', 0),
        server_time=datetime.now().isoformat()
    )
    return status_html

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)

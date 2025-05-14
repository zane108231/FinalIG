import os
import re
import requests
import cloudscraper
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class TikTokDownloader:
    def __init__(self):
        self.scraper = cloudscraper.create_scraper(
            browser={
                'browser': 'chrome',
                'platform': 'windows',
                'mobile': False
            }
        )
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Cache-Control': 'max-age=0'
        }

    def extract_video_id(self, url):
        """Extract video ID from various TikTok URL formats."""
        try:
            # Handle shortened URLs
            if 'vt.tiktok.com' in url:
                response = self.scraper.head(url, allow_redirects=True)
                url = response.url

            # Extract video ID using regex
            patterns = [
                r'/video/(\d+)',  # Standard format
                r'video/(\d+)',   # Alternative format
                r'v=(\d+)',       # Query parameter format
                r'/(\d+)/?$'      # Direct ID format
            ]

            for pattern in patterns:
                match = re.search(pattern, url)
                if match:
                    return match.group(1)

            raise ValueError("Could not extract video ID from URL")

        except Exception as e:
            logger.error(f"Error extracting video ID: {str(e)}")
            raise

    def get_video_url(self, video_id):
        """Get video URL without watermark."""
        try:
            # Use ssstik.io API to get video without watermark
            api_url = f"https://ssstik.io/abc?url=https://www.tiktok.com/@tiktok/video/{video_id}"
            
            # First request to get the token
            response = self.scraper.get(api_url, headers=self.headers)
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Extract the token
            token = soup.find('input', {'name': 'token'})['value']
            
            # Prepare data for the second request
            data = {
                'id': video_id,
                'token': token,
                'tt_watermark': 'off'
            }
            
            # Second request to get the download URL
            response = self.scraper.post(api_url, data=data, headers=self.headers)
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Find the download link
            download_link = soup.find('a', {'class': 'pure-button pure-button-primary is-center u-bl dl-button download_link without_watermark'})
            
            if not download_link:
                raise ValueError("Could not find download link")
                
            return download_link['href']

        except Exception as e:
            logger.error(f"Error getting video URL: {str(e)}")
            raise

    def download_video(self, url, output_dir='downloads'):
        """
        Download TikTok video without watermark.
        
        Args:
            url (str): TikTok video URL (any format)
            output_dir (str): Directory to save the video
            
        Returns:
            str: Path to the downloaded video
        """
        try:
            # Create output directory if it doesn't exist
            os.makedirs(output_dir, exist_ok=True)
            
            # Extract video ID
            video_id = self.extract_video_id(url)
            logger.info(f"Extracted video ID: {video_id}")
            
            # Get video URL without watermark
            video_url = self.get_video_url(video_id)
            logger.info("Got video URL without watermark")
            
            # Download the video
            response = self.scraper.get(video_url, headers=self.headers, stream=True)
            video_path = os.path.join(output_dir, f"tiktok_{video_id}.mp4")
            
            with open(video_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            
            logger.info(f"Video downloaded successfully: {video_path}")
            return video_path
            
        except Exception as e:
            logger.error(f"Error downloading video: {str(e)}")
            raise

def main():
    # Example usage
    downloader = TikTokDownloader()
    
    # Test with different URL formats
    test_urls = [
        "https://www.tiktok.com/@username/video/123456789",
        "https://vt.tiktok.com/ZShye2gFt/",
        "https://vm.tiktok.com/123456789/",
        "https://tiktok.com/t/123456789/"
    ]
    
    for url in test_urls:
        try:
            print(f"\nTesting URL: {url}")
            video_path = downloader.download_video(url)
            print(f"Successfully downloaded to: {video_path}")
        except Exception as e:
            print(f"Failed to download: {str(e)}")

if __name__ == "__main__":
    main() 
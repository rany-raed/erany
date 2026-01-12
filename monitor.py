#!/usr/bin/env python3
"""
TikTok Monitor - GitHub Actions Version
Monitors TikTok accounts and sends Slack alerts for 10K+ views
"""

import os
import sys
import json
import time
import sqlite3
import requests
from datetime import datetime

# Add TikTok Scraper to path
sys.path.insert(0, 'TikTok-Content-Scraper')
from TT_Content_Scraper import TT_Content_Scraper

# Configuration
SLACK_WEBHOOK = os.getenv('SLACK_WEBHOOK', '')
ACCOUNTS = [acc.strip() for acc in os.getenv('ACCOUNTS', '').split(',') if acc.strip()]
THRESHOLD = int(os.getenv('THRESHOLD', '10000'))

# Initialize TikTok Scraper
scraper = TT_Content_Scraper(
    wait_time=0.5,
    output_files_fp="temp/",
    progress_file_fn="scraper.db",
    clear_console=False
)

class Database:
    """Simple database for tracking videos"""
    
    def __init__(self):
        self.db = 'monitor_state.db'
        self.init()
    
    def init(self):
        conn = sqlite3.connect(self.db)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS videos (
            video_id TEXT PRIMARY KEY,
            username TEXT,
            views INTEGER,
            alert_sent INTEGER DEFAULT 0,
            checked_at TEXT
        )''')
        conn.commit()
        conn.close()
    
    def should_alert(self, video_id, views):
        conn = sqlite3.connect(self.db)
        c = conn.cursor()
        c.execute('SELECT alert_sent FROM videos WHERE video_id=?', (video_id,))
        result = c.fetchone()
        conn.close()
        return views >= THRESHOLD and (result is None or result[0] == 0)
    
    def save(self, video_id, username, views):
        conn = sqlite3.connect(self.db)
        c = conn.cursor()
        c.execute('''INSERT OR REPLACE INTO videos 
                     (video_id, username, views, checked_at) 
                     VALUES (?, ?, ?, ?)''',
                  (video_id, username, views, datetime.now().isoformat()))
        conn.commit()
        conn.close()
    
    def mark_sent(self, video_id):
        conn = sqlite3.connect(self.db)
        c = conn.cursor()
        c.execute('UPDATE videos SET alert_sent=1 WHERE video_id=?', (video_id,))
        conn.commit()
        conn.close()

def send_slack_alert(video):
    """Send alert to Slack"""
    if not SLACK_WEBHOOK:
        print("⚠️ No Slack webhook configured")
        return False
    
    message = {
        "blocks": [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "🔥 Trending Video Alert!", "emoji": True}
            },
            {"type": "divider"},
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Platform:*\nTikTok"},
                    {"type": "mrkdwn", "text": f"*Account:*\n@{video['username']}"}
                ]
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Views:*\n{video['views']:,}"},
                    {"type": "mrkdwn", "text": f"*Time:*\n{datetime.now().strftime('%Y-%m-%d %H:%M')}"}
                ]
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Title:*\n{video['title'][:200]}"}
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"<{video['url']}|🔗 View Video>"}
            },
            {
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": "🤖 Powered by GitHub Actions"}
                ]
            }
        ]
    }
    
    try:
        response = requests.post(SLACK_WEBHOOK, json=message, timeout=10)
        if response.status_code == 200:
            print(f"✅ Alert sent: @{video['username']} - {video['views']:,} views")
            return True
        else:
            print(f"❌ Slack error: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Error sending alert: {e}")
        return False

def get_videos(username):
    """Get videos for a TikTok user"""
    print(f"📱 Checking @{username}...")
    
    try:
        # Add user to scraper
        scraper.add_objects(ids=[username], title=f"monitor_{username}", type="user")
        
        # Scrape user
        scraper.scrape_pending(only_users=True, scrape_files=False)
        
        # Read user data
        user_file = f"temp/user_metadata/{username}.json"
        if not os.path.exists(user_file):
            print(f"  ⚠️ No data found for @{username}")
            return []
        
        with open(user_file, 'r', encoding='utf-8') as f:
            user_data = json.load(f)
        
        videos = []
        items = user_data.get('itemList', [])[:10]
        
        if items:
            video_ids = [item.get('id') for item in items if item.get('id')]
            
            if video_ids:
                scraper.add_objects(ids=video_ids, title=f"from_{username}", type="content")
                scraper.scrape_pending(only_content=True, scrape_files=False)
                
                for item in items:
                    video_id = item.get('id')
                    if not video_id:
                        continue
                    
                    video_file = f"temp/content_metadata/{video_id}.json"
                    
                    if os.path.exists(video_file):
                        with open(video_file, 'r', encoding='utf-8') as f:
                            video_data = json.load(f)
                        
                        stats = video_data.get('stats', {})
                        views = stats.get('playCount', 0)
                        
                        videos.append({
                            'video_id': video_id,
                            'username': username,
                            'title': video_data.get('desc', 'No title'),
                            'views': views,
                            'url': f"https://www.tiktok.com/@{username}/video/{video_id}"
                        })
        
        print(f"  ✅ Found {len(videos)} videos")
        return videos
        
    except Exception as e:
        print(f"  ❌ Error: {e}")
        return []

def main():
    """Main function"""
    print("\n" + "="*70)
    print("🚀 TIKTOK MONITOR STARTING")
    print("="*70)
    print(f"⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📱 Accounts to check: {len(ACCOUNTS)}")
    print(f"🎯 Alert threshold: {THRESHOLD:,} views")
    print(f"🔔 Slack: {'✅ Configured' if SLACK_WEBHOOK else '❌ Not configured'}")
    print("="*70 + "\n")
    
    if not SLACK_WEBHOOK:
        print("❌ ERROR: SLACK_WEBHOOK not configured!")
        return
    
    if not ACCOUNTS:
        print("❌ ERROR: No accounts configured!")
        return
    
    db = Database()
    new_alerts = 0
    total_videos = 0
    
    for account in ACCOUNTS:
        try:
            videos = get_videos(account)
            total_videos += len(videos)
            
            for video in videos:
                db.save(video['video_id'], video['username'], video['views'])
                
                if db.should_alert(video['video_id'], video['views']):
                    print(f"🎯 ALERT: @{video['username']} - {video['views']:,} views")
                    
                    if send_slack_alert(video):
                        db.mark_sent(video['video_id'])
                        new_alerts += 1
            
            time.sleep(2)
            
        except Exception as e:
            print(f"❌ Error checking @{account}: {e}")
            continue
    
    print(f"\n{'='*70}")
    print(f"✅ MONITORING COMPLETE")
    print("="*70)
    print(f"📊 Total videos checked: {total_videos}")
    print(f"📤 New alerts sent: {new_alerts}")
    print(f"⏰ Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*70 + "\n")

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n⛔ Stopped by user")
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        raise
```

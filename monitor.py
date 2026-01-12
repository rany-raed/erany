#!/usr/bin/env python3
import os
import sys
import json
import time
import sqlite3
import requests
from datetime import datetime

sys.path.insert(0, 'TikTok-Content-Scraper')
from TT_Content_Scraper import TT_Content_Scraper

SLACK_WEBHOOK = os.getenv('SLACK_WEBHOOK', '')
ACCOUNTS = os.getenv('ACCOUNTS', '').split(',')
THRESHOLD = int(os.getenv('THRESHOLD', '10000'))

class Database:
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

def send_slack(video):
    if not SLACK_WEBHOOK:
        return False
    
    message = {
        "blocks": [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "Trending Video Alert"}
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Account:* @{video['username']}"},
                    {"type": "mrkdwn", "text": f"*Views:* {video['views']:,}"}
                ]
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Title:* {video['title'][:150]}"}
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"<{video['url']}|View Video>"}
            }
        ]
    }
    
    try:
        response = requests.post(SLACK_WEBHOOK, json=message, timeout=10)
        if response.status_code == 200:
            print(f"Alert sent: {video['username']}")
            return True
    except:
        pass
    return False

def get_videos(username):
    print(f"Checking {username}...")
    try:
        scraper = TT_Content_Scraper(
            wait_time=0.5,
            output_files_fp="temp/",
            progress_file_fn=f"sc_{username}.db",
            clear_console=False
        )
        
        scraper.add_objects(ids=[username], title=f"m_{username}", type="user")
        scraper.scrape_pending(only_users=True, scrape_files=False)
        
        user_file = f"temp/user_metadata/{username}.json"
        if not os.path.exists(user_file):
            print(f"No data for {username}")
            return []
        
        with open(user_file, 'r') as f:
            user_data = json.load(f)
        
        videos = []
        items = user_data.get('itemList', [])[:10]
        
        if items:
            video_ids = [item.get('id') for item in items if item.get('id')]
            if video_ids:
                scraper.add_objects(ids=video_ids, title=f"v_{username}", type="content")
                scraper.scrape_pending(only_content=True, scrape_files=False)
                
                for item in items:
                    video_id = item.get('id')
                    if not video_id:
                        continue
                    video_file = f"temp/content_metadata/{video_id}.json"
                    if os.path.exists(video_file):
                        with open(video_file, 'r') as f:
                            video_data = json.load(f)
                        stats = video_data.get('stats', {})
                        videos.append({
                            'video_id': video_id,
                            'username': username,
                            'title': video_data.get('desc', 'No title'),
                            'views': stats.get('playCount', 0),
                            'url': f"https://www.tiktok.com/@{username}/video/{video_id}"
                        })
        
        print(f"Found {len(videos)} videos")
        return videos
    except Exception as e:
        print(f"Error for {username}: {e}")
        return []

def main():
    print("TikTok Monitor Starting...")
    print(f"Accounts: {len([a for a in ACCOUNTS if a.strip()])}")
    print(f"Threshold: {THRESHOLD:,}")
    
    if not SLACK_WEBHOOK:
        print("No webhook configured!")
        return
    
    db = Database()
    alerts = 0
    
    for account in ACCOUNTS:
        if not account.strip():
            continue
        videos = get_videos(account.strip())
        for video in videos:
            db.save(video['video_id'], video['username'], video['views'])
            if db.should_alert(video['video_id'], video['views']):
                print(f"ALERT: {video['username']} - {video['views']:,} views")
                if send_slack(video):
                    db.mark_sent(video['video_id'])
                    alerts += 1
        time.sleep(2)
    
    print(f"Completed! Alerts sent: {alerts}")

if __name__ == '__main__':
    main()

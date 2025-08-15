import os
import asyncio
import logging
import re
import signal
import sys
import argparse
import yaml
from telethon import TelegramClient, events
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, PhoneNumberInvalidError
from typing import Optional
import time
import json
from datetime import datetime, date

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('userbot_forwarder.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# --- Configuration for Userbot ---
def load_config():
    """Load configuration from YAML file"""
    config_file = 'env_vars-userbot.yml'
    try:
        with open(config_file, 'r') as f:
            config = yaml.safe_load(f)
        return config
    except Exception as e:
        print(f"Error loading config file: {e}")
        return {}

# Load config
config = load_config()

API_ID = int(config.get('TELEGRAM_API_ID', '27567587'))
API_HASH = config.get('TELEGRAM_API_HASH', 'dd20d2e57837adccf9da7d7ee49c13d6')
BOT_USERNAME = config.get('TELEGRAM_BOT_USERNAME', 'AfterhoursFWL_Bot')

# Duplicate message handling configuration
DUPLICATE_IGNORE_DURATION = int(config.get('DUPLICATE_IGNORE_DURATION', '3600'))  # Default: 1 hour in seconds
DUPLICATE_CHECK_ENABLED = config.get('DUPLICATE_CHECK_ENABLED', 'true').lower() == 'true'

SESSION_NAME = 'driver_forwarding_session'
SESSION_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), f'{SESSION_NAME}.session')

# Global variables for graceful shutdown
client = None
shutdown_event = asyncio.Event()

class UserbotForwarder:
    def __init__(self):
        self.client = TelegramClient(SESSION_NAME, API_ID, API_HASH)
        self.bot_entity = None
        self.retry_count = 0
        self.max_retries = 5
        self.retry_delay = 30  # seconds
        
        # Daily message tracking
        self.daily_messages_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'daily_messages.json')
        self.forwarded_today = self.load_daily_messages()
        
        # Message tracking for duplicate handling
        self.message_tracking_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'message_tracking.json')
        self.message_tracking = self.load_message_tracking()
        
        # Clean up old tracking data on startup
        self.cleanup_old_tracking_data()
        
    def load_daily_messages(self) -> dict:
        """Load today's forwarded messages from file"""
        today = str(date.today())
        try:
            if os.path.exists(self.daily_messages_file):
                with open(self.daily_messages_file, 'r') as f:
                    data = json.load(f)
                    # Return today's data, or empty dict if it's a new day
                    if data.get('date') == today:
                        return data.get('forwarded_users', {})
                    else:
                        logger.info(f"New day detected. Resetting forwarded messages tracking.")
                        return {}
            return {}
        except Exception as e:
            logger.error(f"Error loading daily messages file: {e}")
            return {}
    
    def save_daily_messages(self):
        """Save today's forwarded messages to file"""
        today = str(date.today())
        data = {
            'date': today,
            'forwarded_users': self.forwarded_today
        }
        try:
            with open(self.daily_messages_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving daily messages file: {e}")
    
    def load_message_tracking(self) -> dict:
        """Load message tracking data from file"""
        try:
            if os.path.exists(self.message_tracking_file):
                with open(self.message_tracking_file, 'r') as f:
                    data = json.load(f)
                    return data
            return {'ignored': {}, 'collected': {}}
        except Exception as e:
            logger.error(f"Error loading message tracking file: {e}")
            return {'ignored': {}, 'collected': {}}
    
    def save_message_tracking(self):
        """Save message tracking data to file"""
        try:
            with open(self.message_tracking_file, 'w') as f:
                json.dump(self.message_tracking, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving message tracking file: {e}")
    
    def cleanup_old_tracking_data(self):
        """Remove tracking data older than the ignore duration"""
        if not DUPLICATE_CHECK_ENABLED:
            return
            
        current_time = time.time()
        cutoff_time = current_time - DUPLICATE_IGNORE_DURATION
        
        # Clean ignored messages
        cleaned_ignored = {}
        for user_id, data in self.message_tracking['ignored'].items():
            if data.get('timestamp', 0) > cutoff_time:
                cleaned_ignored[user_id] = data
        
        # Clean collected messages
        cleaned_collected = {}
        for user_id, data in self.message_tracking['collected'].items():
            if data.get('timestamp', 0) > cutoff_time:
                cleaned_collected[user_id] = data
        
        self.message_tracking['ignored'] = cleaned_ignored
        self.message_tracking['collected'] = cleaned_collected
        self.save_message_tracking()
        
        logger.info(f"Cleaned up tracking data. Kept {len(cleaned_ignored)} ignored and {len(cleaned_collected)} collected entries.")
    
    def has_forwarded_today(self, user_id: int) -> bool:
        """Check if we've already forwarded a message from this user today"""
        return str(user_id) in self.forwarded_today
    
    def mark_as_forwarded(self, user_id: int, sender_name: str):
        """Mark this user as having a message forwarded today"""
        self.forwarded_today[str(user_id)] = {
            'name': sender_name,
            'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        self.save_daily_messages()
        
    def track_ignored_message(self, user_id: int, sender_name: str, reason: str):
        """Track a message that was ignored"""
        if not DUPLICATE_CHECK_ENABLED:
            return
            
        current_time = time.time()
        self.message_tracking['ignored'][str(user_id)] = {
            'name': sender_name,
            'timestamp': current_time,
            'reason': reason,
            'time_formatted': datetime.fromtimestamp(current_time).strftime('%Y-%m-%d %H:%M:%S')
        }
        self.save_message_tracking()
        logger.info(f"Tracked ignored message from {sender_name} (ID: {user_id}) - Reason: {reason}")
    
    def track_collected_message(self, user_id: int, sender_name: str):
        """Track a message that was collected/forwarded"""
        if not DUPLICATE_CHECK_ENABLED:
            return
            
        current_time = time.time()
        self.message_tracking['collected'][str(user_id)] = {
            'name': sender_name,
            'timestamp': current_time,
            'time_formatted': datetime.fromtimestamp(current_time).strftime('%Y-%m-%d %H:%M:%S')
        }
        self.save_message_tracking()
        logger.info(f"Tracked collected message from {sender_name} (ID: {user_id})")
    
    def is_message_recently_handled(self, user_id: int) -> bool:
        """Check if a message from this user was recently handled (within ignore duration)"""
        if not DUPLICATE_CHECK_ENABLED:
            return False
            
        current_time = time.time()
        cutoff_time = current_time - DUPLICATE_IGNORE_DURATION
        
        # Check ignored messages
        if str(user_id) in self.message_tracking['ignored']:
            if self.message_tracking['ignored'][str(user_id)].get('timestamp', 0) > cutoff_time:
                return True
        
        # Check collected messages
        if str(user_id) in self.message_tracking['collected']:
            if self.message_tracking['collected'][str(user_id)].get('timestamp', 0) > cutoff_time:
                return True
        
        return False
        
    def get_tracking_stats(self) -> dict:
        """Get current tracking statistics"""
        if not DUPLICATE_CHECK_ENABLED:
            return {'enabled': False}
            
        current_time = time.time()
        cutoff_time = current_time - DUPLICATE_IGNORE_DURATION
        
        # Count recent entries
        recent_ignored = sum(1 for data in self.message_tracking['ignored'].values() 
                           if data.get('timestamp', 0) > cutoff_time)
        recent_collected = sum(1 for data in self.message_tracking['collected'].values() 
                             if data.get('timestamp', 0) > cutoff_time)
        
        return {
            'enabled': True,
            'ignore_duration_seconds': DUPLICATE_IGNORE_DURATION,
            'ignore_duration_hours': DUPLICATE_IGNORE_DURATION / 3600,
            'recent_ignored': recent_ignored,
            'recent_collected': recent_collected,
            'total_ignored': len(self.message_tracking['ignored']),
            'total_collected': len(self.message_tracking['collected']),
            'last_cleanup': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
    
    def display_tracking_info(self):
        """Display current tracking information"""
        stats = self.get_tracking_stats()
        
        if not stats['enabled']:
            logger.info("Message tracking is disabled")
            return
        
        logger.info("=== Message Tracking Configuration ===")
        logger.info(f"Ignore Duration: {stats['ignore_duration_hours']:.1f} hours ({stats['ignore_duration_seconds']} seconds)")
        logger.info(f"Recent Ignored Messages: {stats['recent_ignored']}")
        logger.info(f"Recent Collected Messages: {stats['recent_collected']}")
        logger.info(f"Total Ignored (all time): {stats['total_ignored']}")
        logger.info(f"Total Collected (all time): {stats['total_collected']}")
        logger.info(f"Last Cleanup: {stats['last_cleanup']}")
        logger.info("=====================================")
        
    async def start_periodic_cleanup(self):
        """Start periodic cleanup of old tracking data"""
        if not DUPLICATE_CHECK_ENABLED:
            return
            
        async def cleanup_task():
            while not shutdown_event.is_set():
                try:
                    # Wait for the cleanup interval (half of ignore duration)
                    cleanup_interval = max(DUPLICATE_IGNORE_DURATION // 2, 300)  # At least 5 minutes
                    await asyncio.sleep(cleanup_interval)
                    
                    if not shutdown_event.is_set():
                        self.cleanup_old_tracking_data()
                        
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Error in periodic cleanup: {e}")
                    await asyncio.sleep(60)  # Wait a minute before retrying
        
        # Start the cleanup task
        asyncio.create_task(cleanup_task())
        logger.info(f"Started periodic cleanup task (every {max(DUPLICATE_IGNORE_DURATION // 2, 300)} seconds)")
        
    async def setup_client(self):
        """Initialize and authenticate the Telegram client"""
        try:
            logger.info("Starting Telegram client...")
            await self.client.start()
            
            # Get bot entity once and cache it
            self.bot_entity = await self.client.get_entity(BOT_USERNAME)
            logger.info(f"Successfully connected to bot: {BOT_USERNAME}")
            
            # Register event handler for private messages
            self.client.add_event_handler(self.handle_new_message, events.NewMessage(incoming=True, func=lambda e: e.is_private))
            logger.info("Event handler registered successfully")
            
            # Display tracking configuration
            self.display_tracking_info()
            
            # Start periodic cleanup task
            await self.start_periodic_cleanup()
            
            return True
            
        except SessionPasswordNeededError:
            logger.error("Two-factor authentication is enabled. Please provide your password.")
            return False
        except PhoneNumberInvalidError:
            logger.error("Invalid phone number. Please check your credentials.")
            return False
        except Exception as e:
            logger.error(f"Error setting up client: {e}")
            return False

    async def handle_new_message(self, event):
        """Handle new incoming private messages and forward them to the bot"""
        try:
            message = event.message
            sender = await message.get_sender()
            
            if not sender:
                logger.warning("Could not get sender information")
                return
            
            # Build sender name
            sender_name = self.build_sender_name(sender)
            sender_id = sender.id
            
            # Check if we've already handled a message from this user recently (within ignore duration)
            if self.is_message_recently_handled(sender_id):
                logger.info(f"Already handled a message from '{sender_name}' (ID: {sender_id}) recently. Skipping.")
                return
            
            # Check if we've already forwarded a message from this user today
            if self.has_forwarded_today(sender_id):
                logger.info(f"Already forwarded a message from '{sender_name}' (ID: {sender_id}) today. Skipping.")
                self.track_ignored_message(sender_id, sender_name, "Already forwarded today")
                return
            
            # Check if the message should be forwarded
            if not self.should_forward_message(message, sender, sender_name):
                logger.info(f"Ignoring message from '{sender_name}' (ID: {sender_id}) - doesn't match criteria")
                self.track_ignored_message(sender_id, sender_name, "Doesn't match forwarding criteria")
                return
            
            logger.info(f"Processing FIRST message today from '{sender_name}' (ID: {sender_id}): {message.text[:50]}...")
            
            # Forward message with sender info
            success = await self.forward_message_with_info(message, sender_name, sender_id)
            
            # Mark as forwarded only if successful
            if success:
                self.mark_as_forwarded(sender_id, sender_name)
                self.track_collected_message(sender_id, sender_name)
                logger.info(f"Marked '{sender_name}' as forwarded for today and tracked as collected")
            else:
                logger.warning(f"Failed to forward message from '{sender_name}' (ID: {sender_id})")
                self.track_ignored_message(sender_id, sender_name, "Forwarding failed")
            
        except Exception as e:
            logger.error(f"Error handling message: {e}")
    
    def build_sender_name(self, sender) -> str:
        """Build a complete name from sender information"""
        name_parts = []
        
        if hasattr(sender, 'first_name') and sender.first_name:
            name_parts.append(sender.first_name.strip())
        
        if hasattr(sender, 'last_name') and sender.last_name:
            name_parts.append(sender.last_name.strip())
        
        if hasattr(sender, 'username') and sender.username:
            username = f"@{sender.username}"
            if name_parts:
                return f"{' '.join(name_parts)} ({username})"
            else:
                return username
        
        return ' '.join(name_parts) if name_parts else f"Unknown User"
    
    def should_forward_message(self, message, sender, sender_name: str) -> bool:
        """Determine if a message should be forwarded based on filtering criteria"""
        # Must have text content
        if not message.text:
            return False
        
        # Check if the sender's name contains a 3-4 digit number or has a first and last name
        has_digits = bool(re.search(r'\d{3,4}', sender_name))
        has_full_name = hasattr(sender, 'first_name') and hasattr(sender, 'last_name') and sender.first_name and sender.last_name
        
        return has_digits or has_full_name
    
    async def forward_message_with_info(self, message, sender_name: str, sender_id: int) -> bool:
        """Forward message to bot with sender information. Returns True if successful."""
        try:
            if not self.bot_entity:
                logger.error("Bot entity not available, trying to reconnect...")
                try:
                    self.bot_entity = await self.client.get_entity(BOT_USERNAME)
                    logger.info(f"Reconnected to bot: {self.bot_entity.username}")
                except Exception as e:
                    logger.error(f"Failed to reconnect to bot: {e}")
                    return False
            
            # Create a formatted message with sender info
            formatted_message = f"📨 FIRST MESSAGE TODAY from: {sender_name}\n" \
                              f"👤 User ID: {sender_id}\n" \
                              f"⏰ Time: {message.date.strftime('%Y-%m-%d %H:%M:%S')}\n" \
                              f"{'='*40}\n" \
                              f"{message.text}"
            
            # Send the formatted message to the specific bot
            logger.info(f"Sending message to bot {self.bot_entity.username} (ID: {self.bot_entity.id})")
            await self.client.send_message(self.bot_entity, formatted_message)
            logger.info(f"Message forwarded successfully from {sender_name} to bot {self.bot_entity.username}")
            return True
            
        except Exception as e:
            logger.error(f"Error forwarding message from {sender_name}: {e}")
            # Try to refresh bot entity on next attempt
            self.bot_entity = None
            return False

    async def run_with_retry(self):
        """Run the userbot with retry logic"""
        while self.retry_count < self.max_retries and not shutdown_event.is_set():
            try:
                if await self.setup_client():
                    logger.info("Userbot is running and listening for private messages...")
                    
                    # Reset retry count on successful connection
                    self.retry_count = 0
                    
                    # Create a task for running the client
                    run_task = asyncio.create_task(self.client.run_until_disconnected())
                    shutdown_task = asyncio.create_task(shutdown_event.wait())
                    
                    # Wait for either the client to disconnect or shutdown signal
                    done, pending = await asyncio.wait(
                        [run_task, shutdown_task], 
                        return_when=asyncio.FIRST_COMPLETED
                    )
                    
                    # Cancel any pending tasks
                    for task in pending:
                        task.cancel()
                        try:
                            await task
                        except asyncio.CancelledError:
                            pass
                    
                    # If shutdown was requested, break the loop
                    if shutdown_event.is_set():
                        logger.info("Shutdown requested, exiting...")
                        break
                    
                else:
                    logger.error("Failed to setup client")
                    break
                    
            except KeyboardInterrupt:
                logger.info("Received keyboard interrupt, shutting down...")
                break
            except Exception as e:
                logger.error(f"Unexpected error: {e}")
                self.retry_count += 1
                
                if self.retry_count < self.max_retries and not shutdown_event.is_set():
                    logger.info(f"Retrying in {self.retry_delay} seconds... (Attempt {self.retry_count}/{self.max_retries})")
                    try:
                        await asyncio.wait_for(shutdown_event.wait(), timeout=self.retry_delay)
                        break  # Shutdown requested during delay
                    except asyncio.TimeoutError:
                        continue  # Continue with retry
                else:
                    logger.error("Max retries reached or shutdown requested, giving up")
                    break
            
            finally:
                if self.client and self.client.is_connected():
                    try:
                        await self.client.disconnect()
                        logger.info("Client disconnected successfully")
                    except Exception as e:
                        logger.error(f"Error disconnecting client: {e}")

def signal_handler(signum, frame):
    """Handle shutdown signals gracefully"""
    logger.info(f"Received signal {signum}, initiating shutdown...")
    shutdown_event.set()
    # Force disconnect the client if it exists
    if 'client' in globals() and client and client.is_connected():
        try:
            asyncio.create_task(client.disconnect())
        except:
            pass

def parse_arguments():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(description='Telegram Userbot Forwarder with Message Tracking')
    parser.add_argument('--stats', action='store_true', help='Show tracking statistics and exit')
    parser.add_argument('--ignore-duration', type=int, help='Set ignore duration in seconds (overrides environment variable)')
    parser.add_argument('--enable-tracking', action='store_true', help='Enable message tracking (overrides environment variable)')
    parser.add_argument('--disable-tracking', action='store_true', help='Disable message tracking (overrides environment variable)')
    
    return parser.parse_args()

def show_tracking_stats():
    """Display tracking statistics from saved files"""
    try:
        # Load tracking data
        tracking_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'message_tracking.json')
        daily_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'daily_messages.json')
        
        print("=== Message Tracking Statistics ===")
        
        # Show configuration
        ignore_duration = int(os.environ.get('DUPLICATE_IGNORE_DURATION', '3600'))
        tracking_enabled = os.environ.get('DUPLICATE_CHECK_ENABLED', 'true').lower() == 'true'
        
        print(f"Tracking Enabled: {tracking_enabled}")
        print(f"Ignore Duration: {ignore_duration / 3600:.1f} hours ({ignore_duration} seconds)")
        
        if tracking_enabled and os.path.exists(tracking_file):
            with open(tracking_file, 'r') as f:
                tracking_data = json.load(f)
            
            current_time = time.time()
            cutoff_time = current_time - ignore_duration
            
            # Count recent entries
            recent_ignored = sum(1 for data in tracking_data.get('ignored', {}).values() 
                               if data.get('timestamp', 0) > cutoff_time)
            recent_collected = sum(1 for data in tracking_data.get('collected', {}).values() 
                                 if data.get('timestamp', 0) > cutoff_time)
            
            print(f"\nRecent Activity (last {ignore_duration / 3600:.1f} hours):")
            print(f"  Ignored Messages: {recent_ignored}")
            print(f"  Collected Messages: {recent_collected}")
            
            print(f"\nAll Time Totals:")
            print(f"  Total Ignored: {len(tracking_data.get('ignored', {}))}")
            print(f"  Total Collected: {len(tracking_data.get('collected', {}))}")
            
            # Show some recent ignored messages
            if tracking_data.get('ignored'):
                print(f"\nRecent Ignored Messages:")
                sorted_ignored = sorted(tracking_data['ignored'].items(), 
                                      key=lambda x: x[1].get('timestamp', 0), reverse=True)
                for user_id, data in sorted_ignored[:5]:  # Show last 5
                    if data.get('timestamp', 0) > cutoff_time:
                        print(f"  {data.get('name', 'Unknown')} (ID: {user_id}) - {data.get('reason', 'No reason')} - {data.get('time_formatted', 'Unknown time')}")
            
            # Show some recent collected messages
            if tracking_data.get('collected'):
                print(f"\nRecent Collected Messages:")
                sorted_collected = sorted(tracking_data['collected'].items(), 
                                        key=lambda x: x[1].get('timestamp', 0), reverse=True)
                for user_id, data in sorted_collected[:5]:  # Show last 5
                    if data.get('timestamp', 0) > cutoff_time:
                        print(f"  {data.get('name', 'Unknown')} (ID: {user_id}) - {data.get('time_formatted', 'Unknown time')}")
        
        # Show daily stats
        if os.path.exists(daily_file):
            with open(daily_file, 'r') as f:
                daily_data = json.load(f)
            
            print(f"\nDaily Forwarding Stats:")
            print(f"  Date: {daily_data.get('date', 'Unknown')}")
            print(f"  Users Forwarded Today: {len(daily_data.get('forwarded_users', {}))}")
            
            if daily_data.get('forwarded_users'):
                print(f"  Recent Forwarded Users:")
                for user_id, data in list(daily_data['forwarded_users'].items())[:5]:  # Show last 5
                    print(f"    {data.get('name', 'Unknown')} (ID: {user_id}) - {data.get('time', 'Unknown time')}")
        
        print("==================================")
        
    except Exception as e:
        print(f"Error reading tracking statistics: {e}")

async def main():
    """Main function to run the userbot"""
    # Parse command line arguments
    args = parse_arguments()
    
    # Override config values with command line arguments
    global DUPLICATE_IGNORE_DURATION, DUPLICATE_CHECK_ENABLED
    
    if args.ignore_duration is not None:
        DUPLICATE_IGNORE_DURATION = args.ignore_duration
        logger.info(f"Override: Ignore duration set to {DUPLICATE_IGNORE_DURATION} seconds ({DUPLICATE_IGNORE_DURATION / 3600:.1f} hours)")
    
    if args.enable_tracking:
        DUPLICATE_CHECK_ENABLED = True
        logger.info("Override: Message tracking enabled")
    elif args.disable_tracking:
        DUPLICATE_CHECK_ENABLED = False
        logger.info("Override: Message tracking disabled")
    
    # Validate configuration
    if not API_ID or not API_HASH:
        logger.error("Error: API credentials not set. Please check env_vars-userbot.yml file.")
        return 1
        
    if not BOT_USERNAME:
        logger.error("Error: Bot username not set. Please set TELEGRAM_BOT_USERNAME.")
        return 1
    
    logger.info(f"Starting userbot with API_ID: {API_ID}")
    logger.info(f"Bot username: {BOT_USERNAME}")
    logger.info(f"Session path: {SESSION_PATH}")
    
    # Setup signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Create and run the forwarder
    forwarder = UserbotForwarder()
    
    try:
        await forwarder.run_with_retry()
        return 0
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        return 1

if __name__ == '__main__':
    args = parse_arguments()
    
    if args.stats:
        show_tracking_stats()
    else:
        try:
            exit_code = asyncio.run(main())
            sys.exit(exit_code)
        except KeyboardInterrupt:
            logger.info(f"Application interrupted by user")
            sys.exit(0)
        except Exception as e:
            logger.error(f"Fatal error in main: {e}")
            sys.exit(1)
# Telegram Userbot Forwarder with Message Tracking

A Telegram userbot that forwards private messages to a bot with intelligent duplicate message handling and comprehensive tracking.

## Features

- **Smart Duplicate Prevention**: Configurable timer to ignore duplicate messages from the same user
- **Message Tracking**: Track which chats have been ignored or collected
- **Daily Limits**: Only forward one message per user per day
- **Automatic Cleanup**: Periodically clean old tracking data
- **Command Line Interface**: View stats and configure settings via command line

## Configuration

### Environment Variables

Create a `.env` file with the following variables:

```bash
# Required Telegram API credentials
TELEGRAM_API_ID=your_api_id_here
TELEGRAM_API_HASH=your_api_hash_here
TELEGRAM_BOT_USERNAME=your_bot_username_here

# Duplicate message handling configuration
DUPLICATE_IGNORE_DURATION=3600  # 1 hour in seconds
DUPLICATE_CHECK_ENABLED=true    # Enable/disable tracking
```

### Duplicate Message Handling

- **`DUPLICATE_IGNORE_DURATION`**: How long to ignore duplicate messages from the same user (in seconds)
  - Default: 3600 seconds (1 hour)
  - Set to 0 to disable duplicate checking
  - Set to higher values for longer ignore periods

- **`DUPLICATE_CHECK_ENABLED`**: Enable or disable the entire tracking system
  - `true`: Enable duplicate message tracking
  - `false`: Disable tracking (all messages will be processed)

## Usage

### Running the Userbot

```bash
# Run with default settings
python userbot_forwarder.py

# Run with custom ignore duration (2 hours)
python userbot_forwarder.py --ignore-duration 7200

# Run with tracking disabled
python userbot_forwarder.py --disable-tracking

# Run with tracking enabled (override env var)
python userbot_forwarder.py --enable-tracking
```

### Viewing Statistics

```bash
# Show tracking statistics and exit
python userbot_forwarder.py --stats
```

This will display:
- Current configuration
- Recent activity (within ignore duration)
- All-time totals
- Recent ignored and collected messages
- Daily forwarding statistics

## How It Works

### Message Processing Flow

1. **Recent Check**: First checks if a message from this user was handled within the ignore duration
2. **Daily Check**: Then checks if a message was already forwarded today
3. **Criteria Check**: Verifies if the message meets forwarding criteria
4. **Forwarding**: If all checks pass, forwards the message and tracks it as collected
5. **Tracking**: All actions (ignore/collect) are tracked with timestamps

### Tracking Data

The system maintains two tracking files:

- **`message_tracking.json`**: Tracks ignored and collected messages with timestamps
- **`daily_messages.json`**: Tracks daily forwarding limits

### Automatic Cleanup

- Old tracking data is automatically cleaned up every half the ignore duration
- Minimum cleanup interval is 5 minutes
- Cleanup runs in the background while the userbot is active

## Examples

### Setting a 30-minute ignore duration

```bash
export DUPLICATE_IGNORE_DURATION=1800
python userbot_forwarder.py
```

### Disabling tracking temporarily

```bash
python userbot_forwarder.py --disable-tracking
```

### Checking stats with custom duration

```bash
export DUPLICATE_IGNORE_DURATION=7200  # 2 hours
python userbot_forwarder.py --stats
```

## Logging

The system provides detailed logging for:
- Message processing decisions
- Tracking operations
- Cleanup operations
- Configuration changes

Check `userbot_forwarder.log` for detailed logs.

## Troubleshooting

### Common Issues

1. **Tracking not working**: Ensure `DUPLICATE_CHECK_ENABLED=true`
2. **Messages still being processed**: Check if ignore duration is set to 0
3. **Stats not showing**: Verify tracking files exist and are readable

### Reset Tracking Data

To reset all tracking data, simply delete the tracking files:
```bash
rm message_tracking.json daily_messages.json
```

The system will recreate them on the next run.

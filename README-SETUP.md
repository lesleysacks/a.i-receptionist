# 🤖 AI Receptionist Bot - Complete Setup & User Guide

A WhatsApp-powered automatic receptionist that handles customer inquiries, books appointments, and sends reminders—all without manual intervention.

---

## 📋 Table of Contents

1. [Overview](#overview)
2. [What You Need (Prerequisites)](#what-you-need-prerequisites)
3. [Step-by-Step Setup](#step-by-step-setup)
4. [Configuration](#configuration)
5. [Running the App](#running-the-app)
6. [How Customers Use It](#how-customers-use-it)
7. [Viewing Booked Leads](#viewing-booked-leads)
8. [Troubleshooting](#troubleshooting)
9. [Features & Capabilities](#features--capabilities)

---

## Overview

### What Does It Do?

This bot automatically responds to WhatsApp messages from your customers. It:

✅ **Answers common questions** about pricing, hours, location, and services  
✅ **Books appointments** through a guided conversation  
✅ **Saves all bookings** to a file for your records  
✅ **Notifies you** when a new booking is made  
✅ **Sends reminders** to customers 24 hours before their appointment  
✅ **Never sleeps** — it's available 24/7  

### Real-World Example

**Customer:** "Hi, do you have availability?"

**Bot:** "Hello 👋 How can we assist you today?"

**Customer:** "I want to book"

**Bot:** "Sure 👍 Please send your name."

**Customer:** "John Smith"

**Bot:** "Thanks John! What date would you like to book? (e.g. 2025-09-30 14:30)"

**Customer:** "2025-09-30 14:00"

**Bot:** "Great. What service do you need for your booking?"

**Customer:** "Installation"

**Bot:** "✅ Booking received! A consultant will contact you shortly."

*(Meanwhile, you get a notification about the new booking.)*

---

## What You Need (Prerequisites)

Before starting, gather these items:

### 1. **Twilio Account** (WhatsApp Integration)
   - Sign up at [twilio.com](https://twilio.com)
   - Create a WhatsApp Sandbox for testing (free)
   - Get your credentials:
     - **Account SID**
     - **Auth Token**
     - **WhatsApp Number** (provided by Twilio, e.g., `whatsapp:+14155238886`)

### 2. **Your Phone Number**
   - The number where booking notifications will be sent
   - Format: `whatsapp:+1234567890` (include country code)

### 3. **Python** (Programming Language)
   - Download Python 3.8+ from [python.org](https://www.python.org/downloads/)
   - Make sure to check "Add Python to PATH" during installation

### 4. **A Text Editor or IDE** (Optional but Helpful)
   - VS Code (free, recommended)
   - Notepad++
   - Or any text editor

### 5. **Internet Connection**
   - Required for Twilio API calls

---

## Step-by-Step Setup

### Step 1: Prepare Your Computer

1. **Create a folder** for this project:
   - Location: `C:\Users\YourName\Documents\AI-Receptionist` (or anywhere you like)

2. **Download the project files** (you should already have these)

### Step 2: Install Python Dependencies

1. **Open Command Prompt** (search "cmd" in Windows)

2. **Navigate to your project folder:**
   ```
   cd C:\Users\YourName\Documents\AI-Receptionist
   ```

3. **Run the setup command:**
   ```
   pip install -r requirements.txt
   ```
   
   This installs all necessary libraries (Flask, Twilio, etc.)

### Step 3: Get Your Twilio Credentials

1. **Go to [Twilio Console](https://console.twilio.com/)**

2. **Find your Account SID and Auth Token** on the dashboard

3. **Set up WhatsApp:**
   - Navigate to: Messaging → Whatsapp → Sandbox
   - You'll see your WhatsApp sandbox number (looks like `whatsapp:+14155238886`)
   - Note down all three values

4. **Prepare your owner phone number** with country code (e.g., `whatsapp:+27636628853`)

---

## Configuration

### The `.env` File (Secret Credentials)

This file holds your login credentials. **Never share it publicly!**

1. **Find or create `.env`** in your project folder

2. **Open it in a text editor** and add these lines:

```env
TWILIO_ACCOUNT_SID="your-account-sid-here"
TWILIO_AUTH_TOKEN="your-auth-token-here"
TWILIO_WHATSAPP_NUMBER="whatsapp:+14155238886"
OWNER_PHONE_NUMBER="whatsapp:+your-phone-number"
FLASK_DEBUG="false"
PORT="5000"
```

**Example:**
```env
TWILIO_ACCOUNT_SID="ACb86c999af3b4c027d84333f53b86a756"
TWILIO_AUTH_TOKEN="682b5fa9be365e73613fc3793642f1ba"
TWILIO_WHATSAPP_NUMBER="whatsapp:+14155238886"
OWNER_PHONE_NUMBER="whatsapp:+27636628853"
FLASK_DEBUG="false"
PORT="5000"
```

3. **Save the file** (Ctrl+S)

---

## Running the App

### Method 1: From Command Prompt (Simple)

1. **Open Command Prompt**

2. **Go to your project folder:**
   ```
   cd C:\Users\YourName\Documents\AI-Receptionist
   ```

3. **Start the server:**
   ```
   python app.py
   ```

4. **You should see:**
   ```
   * Running on http://127.0.0.1:5000
   * Running on http://192.168.1.106:5000
   ```

5. **Keep this window open** — the app is now running!

### Method 2: Using VS Code (Advanced)

1. **Open VS Code**

2. **File → Open Folder** → Select your project folder

3. **Open Terminal** (Ctrl + `)

4. **Type:**
   ```
   python app.py
   ```

### ⚠️ Important: Setting Up Twilio Webhook

For Twilio to send messages to your bot, you need to tell it where to send them:

1. **Go to Twilio Console → WhatsApp → Sandbox**

2. **Find "When a message comes in"**

3. **Set the Webhook URL to:**
   ```
   https://your-domain.com/whatsapp
   ```
   
   If running locally for testing, use **ngrok** to tunnel:
   - Download [ngrok](https://ngrok.com/)
   - Run: `ngrok http 5000`
   - Use the generated HTTPS URL

---

## How Customers Use It

### For Your Customers

Customers interact through WhatsApp. They can:

1. **Ask Questions:**
   - "What's your pricing?"
   - "What are your hours?"
   - "Where are you located?"
   - "What services do you offer?"

2. **Book Appointments:**
   - Send "book" or "appointment"
   - Follow the bot's prompts:
     - Enter their name
     - Enter desired date/time (e.g., `2025-09-30 14:30`)
     - Enter the service they need
   - Bot confirms the booking

3. **Get Reminders:**
   - 24 hours before the appointment, they receive an SMS reminder

---

## Viewing Booked Leads

### Dashboard (Web Interface)

1. **Start the app** (as described above)

2. **Open a browser** and go to:
   ```
   http://localhost:5000/leads
   ```

3. **You'll see a table** of all booked appointments with:
   - Customer name
   - Phone number
   - Booking date/time
   - Service requested
   - When the booking was made

### Leads File

All bookings are also saved in `leads.json` — a text file you can open and edit.

---

## Troubleshooting

### Problem: "ModuleNotFoundError: No module named 'flask'"

**Solution:**
```
pip install flask twilio python-dotenv apscheduler
```

### Problem: "Missing required environment variables"

**Solution:** Your `.env` file is missing or incomplete. Check:
- File is named exactly `.env` (with a dot)
- All required fields are filled in
- No typos in variable names

### Problem: "No module named 'app'"

**Solution:** Make sure you're in the correct folder:
```
cd path/to/your/project
python app.py
```

### Problem: Messages aren't coming through

**Solution:**
1. Check your Twilio account is active and has credits
2. Verify the webhook URL is set correctly in Twilio
3. Check the `.env` credentials are correct
4. Make sure your WhatsApp number is registered with Twilio

### Problem: Bot doesn't respond to my WhatsApp

**Solution:**
1. Did you message the Twilio sandbox number?
2. Is the app still running (`python app.py`)?
3. Check the terminal for error messages

---

## Features & Capabilities

### Bot Knows How to Answer

The bot responds intelligently to keywords:

| Customer Says | Bot Responds |
|---|---|
| "hi", "hello", "hey" | Greeting |
| "price", "cost", "how much" | "Our standard service starts at R750. Would you like to book?" |
| "hours", "open", "time" | "We are open Monday to Friday from 8am to 5pm." |
| "location", "address", "where" | "We are located in Wellington." |
| "services", "service" | "We offer installation, repairs, and servicing." |
| "book", "appointment" | Starts booking flow |
| "thanks", "thank you" | "You're welcome 😊" |
| "bye", "goodbye" | "Thanks for contacting us. Have a great day!" |

### Booking Flow

1. **Bot:** "Please send your name"
2. **Bot:** "What date would you like to book? (e.g. 2025-09-30 14:30)"
3. **Bot:** "What service do you need?"
4. **Bot:** ✅ Confirmation + you get notified

### Automatic Reminders

- Scheduled to send 24 hours before each appointment
- Runs automatically in the background
- No manual intervention needed

### Error Handling

- Gracefully handles bad dates
- Validates phone numbers
- Safe fallback messages if something breaks
- Logs all errors to console

---

## API Endpoints

If you want to integrate with other systems:

| Endpoint | Method | Purpose |
|---|---|---|
| `/` | GET | Health check ("Server running") |
| `/whatsapp` | POST | Receives messages from Twilio |
| `/leads` | GET | View dashboard of all bookings |

---

## Security Notes

⚠️ **Important:**

- **Never commit `.env` to Git** — it contains secrets
- **Never share your Auth Token** publicly
- **Keep your `.env` file private**
- Use `.gitignore` to exclude `.env` from version control

---

## Need Help?

### Quick Checklist

- [ ] Python 3.8+ installed
- [ ] Project folder created
- [ ] Dependencies installed (`pip install -r requirements.txt`)
- [ ] `.env` file configured with Twilio credentials
- [ ] Twilio webhook URL set to `/whatsapp`
- [ ] App running (`python app.py`)
- [ ] Can access `http://localhost:5000`

### Common Errors & Fixes

| Error | Fix |
|---|---|
| "Connection refused" | Make sure `python app.py` is running |
| "404 Not Found" | Check the URL — should be `/leads` or `/whatsapp` |
| "Invalid Twilio credentials" | Verify `.env` values match your Twilio account |
| "No such file: leads.json" | Will be created automatically on first booking |

---

## Next Steps

1. ✅ Install dependencies
2. ✅ Configure `.env`
3. ✅ Run `python app.py`
4. ✅ Test with a sample message
5. ✅ View bookings at `http://localhost:5000/leads`

---

## Questions?

If something doesn't work:

1. **Check the terminal output** — error messages often explain what's wrong
2. **Verify your `.env` file** — most issues stem from missing credentials
3. **Make sure the app is running** — you should see `Running on http://...`
4. **Review the troubleshooting section** above

---

**Happy automating! 🚀**

Your receptionist bot is now ready to work 24/7.

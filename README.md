# Locus
A macOS focus app that blocks distracting apps and websites during study
sessions.

Website: **https://getlocusapp.netlify.app**

## Install

1. Download the latest **Locus.dmg** from the
   [Releases page](../../releases/latest).
2. Open the DMG and drag **Locus** into your **Applications** folder.
3. First launch: right-click **Locus** → **Open** → **Open** (the app
   isn't notarized yet, so macOS warns once).

## 

## Features
- **AI Unblocks**
Unblock websites & apps by explaining why you need them and how they pertain to your task. AI then decides if your reason is valid.
- **Smart Blocking**
Blocks all websites & apps other than the ones on your allow-list and obviously related sites. For example, the AI will not block a google search for "mitosis" during a Science HW session, however it will block the Minecraft app.
- **Calendar & NotionIntegration**
Use the public iCal link to your calendar (Google Calendar, Outlook, Schoology, Canvas, etc) to simply select what task you are working on. Also, if you use Notion as a student planner, use OAuth to connect Locus to it to automatically extract tasks.
- **Drift Detection**
Stay on task on certain websites as the AI re-checks websites. For example, if youtube.com was unblocked because I need to watch a science lecture, but I start watching "Jet Lag: The Game," the AI recognize this and reblock the website.
- **Customization**
The extension is highly customizable. It is also open-source for developer.
- **Analytics**
Understand your behaviors and tendencies with a detailed analytics tab.

## How It Was Made
- **SwiftUI**: Used for building the macOS app's GUI.
- **Python**: Backend for the app, powers all functionality.
- **Cloudflare Workers**: Handles lightweight serverless tasks, such as managing website blocking rules.

## Photo Gallery
- **Main Dashboard**: ![Main Dashboard](dashboard.png)
- **Analytics View**: ![Analytics View](analytics.png)
- **Dark Mode**: ![Dark Mode](darkmode.png)
- **Blocking View**: ![Blocking Settings](blocked.png)

## License
MIT: See [LICENSE](LICENSE).

# 🚀 Publishing Your Animated GitHub Profile README

Your custom animated terminal profile README is ready in this directory!

## Quick Push Instructions

### Step 1: Create the Special Repository on GitHub
1. Go to **[github.com/new](https://github.com/new)**.
2. Under **Repository name**, enter: `aryannn555` *(must match your username exactly)*.
3. Make sure it is set to **Public**.
4. **Do NOT** initialize with README, .gitignore, or license (we already created all files).
5. Click **Create repository**.

---

### Step 2: Push Your Profile Files

Open your terminal, navigate to this `github-profile` directory, and run:

```bash
# Navigate to your profile repository folder
cd "/Users/aryan555/Documents/Projects/github enhancement"

# Initialize git repository
git init
git branch -M main

# Link to your new profile repository
git remote add origin https://github.com/aryannn555/aryannn555.git

# Stage and commit all files
git add .
git commit -m "feat: animated terminal GitHub profile README"

# Push to GitHub
git push -u origin main
```

---

### Step 3: Enable GitHub Actions Write Permissions (For Daily Auto-Updates)

To let the daily cron job automatically refresh your contribution graph every midnight:

1. Go to your repository on GitHub: `https://github.com/aryannn555/aryannn555`
2. Click **Settings** (tab at the top)
3. In the left sidebar, click **Actions** ➔ **General**
4. Scroll down to **Workflow permissions**
5. Select **Read and write permissions**
6. Click **Save**

---

## 🎨 How to Customize

- **Change Avatar Photo**: Replace `assets/avatar.png` with any new square image, then run:
  ```bash
  python3 scripts/generate_profile.py
  ```
- **Edit Info & Tech Stack**: Open `scripts/generate_profile.py` and modify the `specs` list inside `generate_info_card()`, then re-run the script.
- **Run Manually in GitHub**: You can trigger the workflow anytime under the **Actions** tab by selecting **Update Profile Animated SVGs** ➔ **Run workflow**.

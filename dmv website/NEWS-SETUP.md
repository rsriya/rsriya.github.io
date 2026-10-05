# DMV Proton Therapy Collaborative News Agent

This folder adds an automated AI-assisted news feed to the existing
DMV Proton Therapy Collaborative GitHub Pages website.

## Files

```text
news.html
css/news.css
js/news.js
data/news.json
scripts/update_news.py
scripts/requirements.txt
.github/workflows/update-news.yml
```

## 1. Add the files

Copy these files into the root of your existing GitHub Pages repository.

The system assumes your existing shared stylesheet is:

```text
css/style.css
```

The new page loads that stylesheet first and then loads:

```text
css/news.css
```

so the news-specific styles can override shared styles without modifying
your existing CSS.

## 2. Create an OpenAI API key

Create an API key in your OpenAI account.

Do NOT put the key inside:
- news.html
- news.js
- update_news.py
- news.json
- any committed repository file

The browser must never receive the API key.

## 3. Add the key to GitHub

In your repository:

Settings
→ Secrets and variables
→ Actions
→ New repository secret

Name:

```text
OPENAI_API_KEY
```

Value:

```text
your_api_key_here
```

The workflow reads it through:

```yaml
OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
```

## 4. Optional model setting

You can add a repository variable:

```text
OPENAI_NEWS_MODEL
```

For example:

```text
gpt-6-astra
```

If you do not create the variable, the script uses that model as its default.

## 5. Run the agent manually

After pushing the files:

GitHub
→ Actions
→ Update Proton Therapy News
→ Run workflow

The workflow will:

1. install Python dependencies
2. run the AI news agent
3. search the live web
4. identify relevant stories
5. create summaries
6. update data/news.json
7. commit the JSON if it changed

## 6. Automatic updates

The included workflow runs four times each day in
America/New_York time.

You can change the schedule in:

```text
.github/workflows/update-news.yml
```

## 7. How the browser works

The public website does NOT call the OpenAI API.

Instead:

```text
OpenAI
   ↓
GitHub Action
   ↓
data/news.json
   ↓
GitHub Pages
   ↓
news.html
```

This is important because your API key remains private.

## 8. Editorial safeguards

The agent is instructed to:

- search the live web
- prefer authoritative sources
- avoid duplicate stories
- avoid generic cancer stories
- avoid unsupported claims
- provide the original source URL
- write neutral summaries
- keep the latest 18 stories

The website also clearly identifies the original source.

## 9. Initial feed

The included news.json contains a few current seed stories so the page
does not appear empty before the first GitHub Actions run.

The agent will add newer stories and retain the most recent 18.

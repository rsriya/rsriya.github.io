/* =====================================================
   NEWS FEED
===================================================== */

const NEWS_DATA_URL = "../data/news.json";

const researchGrid = document.getElementById("research-grid");
const researchEmpty = document.getElementById("research-empty");

const developmentsGrid = document.getElementById("developments-grid");
const developmentsEmpty = document.getElementById("developments-empty");

const newsUpdated = document.getElementById("news-updated");
const filterButtons = document.querySelectorAll(".news-filter");

let allStories = [];
let activeCategory = "All";


/* -----------------------------------------------------
   HELPERS
----------------------------------------------------- */

function escapeHTML(value) {
    return String(value ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}


function formatDate(dateString) {
    if (!dateString) return "";

    const date = new Date(`${dateString}T12:00:00`);

    if (Number.isNaN(date.getTime())) {
        return dateString;
    }

    return new Intl.DateTimeFormat("en-US", {
        month: "short",
        day: "numeric",
        year: "numeric"
    }).format(date);
}


/* -----------------------------------------------------
   RENDER
----------------------------------------------------- */
function renderCards(stories) {
    return stories
        .map(story => {
            const title = escapeHTML(story.title);
            const summary = escapeHTML(story.summary);
            const source = escapeHTML(story.source);
            const category = escapeHTML(story.category);
            const date = formatDate(story.published_date);
            const url = escapeHTML(story.url);

            return `
                <article class="news-card">

                    <div class="news-card-meta">

                        <span class="news-category">
                            ${category}
                        </span>

                        <time class="news-date" datetime="${escapeHTML(story.published_date)}">
                            ${escapeHTML(date)}
                        </time>

                    </div>

                    <h3>
                        ${title}
                    </h3>

                    <p class="news-card-summary">
                        ${summary}
                    </p>

                    <div class="news-card-footer">

                        <span class="news-source">
                            ${source}
                        </span>

                        <a
                            class="news-read"
                            href="${url}"
                            target="_blank"
                            rel="noopener noreferrer"
                        >
                            Read original
                            <span aria-hidden="true"> →</span>
                        </a>

                    </div>

                </article>
            `;
        })
        .join("");
}

function storyType(story) {
    // Explicit classification takes precedence.
    if (story.content_type === "paper" ||
        story.content_type === "news") {
        return story.content_type;
    }

    // Backward compatibility with existing news.json.
    return /pubmed/i.test(story.source || "")
        ? "paper"
        : "news";
}

function renderNews() {
    const filteredStories = activeCategory === "All"
        ? allStories
        : allStories.filter(
            story => story.category === activeCategory
        );

    const papers = filteredStories.filter(
        story => storyType(story) === "paper"
    );

    const developments = filteredStories.filter(
        story => storyType(story) === "news"
    );

    researchGrid.innerHTML = renderCards(papers);
    researchEmpty.hidden = papers.length > 0;

    developmentsGrid.innerHTML = renderCards(developments);
    developmentsEmpty.hidden = developments.length > 0;
}

/* -----------------------------------------------------
   LOAD
----------------------------------------------------- */

async function loadNews() {

    try {

        const response = await fetch(
            `${NEWS_DATA_URL}?v=${Date.now()}`
        );

        if (!response.ok) {
            throw new Error("Could not load news.json.");
        }

        const data = await response.json();

        allStories = Array.isArray(data.articles)
            ? data.articles
            : [];

        if (data.updated_at) {
            const updated = new Date(data.updated_at);

            if (!Number.isNaN(updated.getTime())) {

                newsUpdated.textContent =
                    `Last updated ${new Intl.DateTimeFormat("en-US", {
                        month: "short",
                        day: "numeric",
                        year: "numeric",
                        hour: "numeric",
                        minute: "2-digit"
                    }).format(updated)}`;
            }
        }

        renderNews();

    } catch (error) {

      const unavailable =
          '<div class="news-loading">News is temporarily unavailable.</div>';
      
      researchGrid.innerHTML = unavailable;
      developmentsGrid.innerHTML = unavailable;
      
      researchEmpty.hidden = true;
      developmentsEmpty.hidden = true;
      newsUpdated.textContent = "";

    }
}


/* -----------------------------------------------------
   FILTERS
----------------------------------------------------- */

filterButtons.forEach(button => {

    button.addEventListener("click", () => {

        filterButtons.forEach(
            item => item.classList.remove("active")
        );

        button.classList.add("active");

        activeCategory =
            button.dataset.category || "All";

        renderNews();
    });

});


loadNews();

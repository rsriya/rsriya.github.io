/* =====================================================
   NEWS FEED
===================================================== */

const NEWS_DATA_URL = "data/news.json";

const newsGrid = document.getElementById("news-grid");
const newsEmpty = document.getElementById("news-empty");
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

function renderNews() {

    const filteredStories =
        activeCategory === "All"
            ? allStories
            : allStories.filter(
                story => story.category === activeCategory
            );

    if (!filteredStories.length) {
        newsGrid.innerHTML = "";
        newsEmpty.hidden = false;
        return;
    }

    newsEmpty.hidden = true;

    newsGrid.innerHTML = filteredStories
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

        console.error(error);

        newsGrid.innerHTML = `
            <div class="news-loading">
                News is temporarily unavailable.
                Please check back soon.
            </div>
        `;

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

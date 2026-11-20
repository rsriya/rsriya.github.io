
/* =====================================================
   DMV PROTON THERAPY COLLABORATIVE
   Events & Conferences
===================================================== */

(() => {

    "use strict";

    const EVENTS_DATA_URL = "../data/events.json";

    // Display completed conferences from the current
    // calendar year and the previous calendar year.
    const ARCHIVE_YEARS = 2;


    /* =================================================
       DATE UTILITIES
    ================================================= */

    function getToday() {

        const parts = new Intl.DateTimeFormat("en-US", {
            timeZone: "America/New_York",
            year: "numeric",
            month: "2-digit",
            day: "2-digit"
        }).formatToParts(new Date());

        const values = Object.fromEntries(
            parts.map(part => [part.type, part.value])
        );

        return `${values.year}-${values.month}-${values.day}`;

    }


    function parseDate(value) {

        if (
            typeof value !== "string" ||
            !/^\d{4}-\d{2}-\d{2}$/.test(value)
        ) {
            return null;
        }

        const date = new Date(`${value}T00:00:00Z`);

        if (Number.isNaN(date.getTime())) {
            return null;
        }

        // Reject invalid calendar dates.
        if (date.toISOString().slice(0, 10) !== value) {
            return null;
        }

        return date;

    }


    function formatDate(value) {

        const date = parseDate(value);

        if (!date) {
            return "";
        }

        return date.toLocaleDateString("en-US", {
            month: "long",
            day: "numeric",
            year: "numeric",
            timeZone: "UTC"
        });

    }


    function formatDateRange(start, end) {

        const startDate = parseDate(start);
        const endDate = parseDate(end);

        if (!startDate || !endDate) {
            return "Dates to be announced";
        }

        if (start === end) {
            return formatDate(start);
        }

        const sameYear =
            startDate.getUTCFullYear() ===
            endDate.getUTCFullYear();

        const sameMonth =
            sameYear &&
            startDate.getUTCMonth() ===
            endDate.getUTCMonth();

        if (sameMonth) {

            const month = startDate.toLocaleDateString(
                "en-US",
                {
                    month: "long",
                    timeZone: "UTC"
                }
            );

            return (
                `${month} ${startDate.getUTCDate()}` +
                `–${endDate.getUTCDate()}, ` +
                `${startDate.getUTCFullYear()}`
            );

        }

        if (sameYear) {

            const options = {
                month: "short",
                day: "numeric",
                timeZone: "UTC"
            };

            return (
                startDate.toLocaleDateString("en-US", options) +
                " – " +
                endDate.toLocaleDateString("en-US", options) +
                `, ${startDate.getUTCFullYear()}`
            );

        }

        return `${formatDate(start)} – ${formatDate(end)}`;

    }



    /* =================================================
       EVENT VALIDATION
    ================================================= */

    function safeURL(value) {

        try {

            const url = new URL(value);

            if (
                url.protocol !== "https:" &&
                url.protocol !== "http:"
            ) {
                return null;
            }

            return url.href;

        } catch {

            return null;

        }

    }


    function validEvent(event) {

        if (!event || typeof event !== "object") {
            return false;
        }

        const required = [
            "title",
            "organization",
            "start_date",
            "end_date",
            "location",
            "url"
        ];

        if (!required.every(
            key =>
                typeof event[key] === "string" &&
                event[key].trim()
        )) {
            return false;
        }

        if (
            !parseDate(event.start_date) ||
            !parseDate(event.end_date)
        ) {
            return false;
        }

        if (event.end_date < event.start_date) {
            return false;
        }

        if (!safeURL(event.url)) {
            return false;
        }

        return true;

    }


    function deduplicateEvents(events) {

        const unique = new Map();

        for (const event of events) {

            const key = [
                event.organization.trim().toLowerCase(),
                event.title.trim().toLowerCase(),
                event.start_date
            ].join("|");

            unique.set(key, event);

        }

        return Array.from(unique.values());

    }


    /* =================================================
       EVENT STATUS
    ================================================= */

    function getEventStatus(event) {

        const today = getToday();

        if (event.end_date < today) {

            return {
                label: "Completed",
                className: "completed"
            };

        }

        if (
            event.start_date <= today &&
            event.end_date >= today
        ) {

            return {
                label: "Ongoing",
                className: "ongoing"
            };

        }

        return {
            label: "Upcoming",
            className: "upcoming"
        };

    }


    /* =================================================
       DOM UTILITIES
    ================================================= */

    function createElement(tag, className, content) {

        const element = document.createElement(tag);

        if (className) {
            element.className = className;
        }

        if (content !== undefined) {
            element.textContent = content;
        }

        return element;

    }


    /* =================================================
       EVENT DEADLINES
    ================================================= */

    function createDeadlines(event) {

        const container = createElement(
            "div",
            "event-deadlines"
        );

        const today = getToday();

        const deadlines = [

            {
                label: "Abstract deadline",
                date: event.abstract_deadline
            },

            {
                label: "Registration deadline",
                date: event.registration_deadline
            }

        ];

        for (const deadline of deadlines) {

            if (!parseDate(deadline.date)) {
                continue;
            }

            // Do not advertise expired deadlines.
            if (deadline.date < today) {
                continue;
            }

            const item = createElement(
                "span",
                "event-deadline"
            );

            const label = createElement(
                "strong",
                "",
                `${deadline.label}: `
            );

            item.append(
                label,
                document.createTextNode(
                    formatDate(deadline.date)
                )
            );

            container.appendChild(item);

        }

        return container.children.length
            ? container
            : null;

    }


    /* =================================================
       EVENT CARD
    ================================================= */


    function createEventCard(event, isPast = false) {
      
          const card = createElement(
              "article",
              "news-card conference-card"
          );
      
          // Organization and category.
      
          const meta = createElement(
              "div",
              "conference-meta"
          );
      
          meta.appendChild(
              createElement(
                  "span",
                  "news-category",
                  event.organization
              )
          );
      
          if (event.category) {
      
              meta.appendChild(
                  createElement(
                      "span",
                      "conference-category",
                      event.category
                  )
              );
      
          }
      
          card.appendChild(meta);
      
      
          // Conference title.
      
          card.appendChild(
              createElement(
                  "h3",
                  "",
                  event.title
              )
          );
      
      
          // Conference dates and location.
      
          const details = createElement(
              "div",
              "conference-details"
          );
      
          details.append(
      
              createElement(
                  "p",
                  "conference-date",
                  formatDateRange(
                      event.start_date,
                      event.end_date
                  )
              ),
      
              createElement(
                  "p",
                  "conference-location",
                  event.location
              )
      
          );
      
          card.appendChild(details);
      
      
          // Display status only for ongoing events.
      
          if (!isPast) {
      
              const status = getEventStatus(event);
      
              if (status.className === "ongoing") {
      
                  card.appendChild(
                      createElement(
                          "span",
                          "event-status ongoing",
                          "Ongoing"
                      )
                  );
      
              }
      
              // Show available upcoming deadlines.
      
              const deadlines = createDeadlines(event);
      
              if (deadlines) {
      
                  card.appendChild(deadlines);
      
              }
      
          }
      
      
          // Conference website.
      
          const footer = createElement(
              "div",
              "news-card-footer"
          );
      
          const link = createElement(
              "a",
              "news-read",
              isPast
                  ? "Event Details ↗"
                  : "Conference Details ↗"
          );
      
          link.href = safeURL(event.url);
          link.target = "_blank";
          link.rel = "noopener noreferrer";
      
          link.setAttribute(
              "aria-label",
              `Official event details for ${event.title}`
          );
      
          footer.appendChild(link);
      
          card.appendChild(footer);
      
          return card;
      
    }
      


    /* =================================================
       RENDER UPCOMING EVENTS
    ================================================= */

    function renderUpcomingEvents(events) {

        const container = document.getElementById(
            "upcoming-events"
        );

        const empty = document.getElementById(
            "upcoming-events-empty"
        );

        container.replaceChildren();
        container.classList.remove("events-list");
        container.classList.add("news-grid");
        const today = getToday();
         
        const currentYear = Number(today.slice(0, 4));
         
        const upcoming = events
             .filter(event => {
                 const eventYear = Number(
                     event.start_date.slice(0, 4)
                 );
         
                 return (
                     event.end_date >= today &&
                     eventYear <= currentYear + 1
                 );
             })
             .sort((a, b) =>
                 a.start_date.localeCompare(b.start_date)
             );

        empty.hidden = upcoming.length > 0;

        for (const event of upcoming) {

            container.appendChild(
                createEventCard(event)
            );

        }

    }


    /* =================================================
       RENDER PAST EVENTS
    ================================================= */

    function renderPastEvents(events) {

        const container = document.getElementById(
            "past-events"
        );

        const empty = document.getElementById(
            "past-events-empty"
        );

        container.replaceChildren();

        const today = getToday();

        const currentYear = Number(
            today.slice(0, 4)
        );

        const earliestYear =
            currentYear - ARCHIVE_YEARS + 1;

        const past = events

            .filter(event => {

                const year = Number(
                    event.end_date.slice(0, 4)
                );

                return (
                    event.end_date < today &&
                    year >= earliestYear
                );

            })

            .sort((a, b) =>
                b.start_date.localeCompare(a.start_date)
            );

        empty.hidden = past.length > 0;

        if (!past.length) {
            return;
        }


        // Group completed conferences by year.

        const groups = new Map();

        for (const event of past) {

            const year = event.end_date.slice(0, 4);

            if (!groups.has(year)) {

                groups.set(year, []);

            }

            groups.get(year).push(event);

        }


        // Display the most recent year first.

        const years = Array.from(groups.keys())
            .sort((a, b) => Number(b) - Number(a));

        for (const year of years) {

            const group = createElement(
                "div",
                "events-year-group"
            );

            group.appendChild(

                createElement(
                    "h4",
                    "events-year-heading",
                    year
                )

            );

            const grid = createElement(
                "div",
                "news-grid conference-grid"
            );
            
            for (const event of groups.get(year)) {
            
                grid.appendChild(
                    createEventCard(event, true)
                );
            
            }
            
            group.appendChild(grid);
            
            container.appendChild(group);

        }

    }


    /* =================================================
       LAST UPDATED
    ================================================= */

    function renderUpdatedTime(value) {

        const element = document.getElementById(
            "events-updated"
        );

        if (!element) {
            return;
        }

        if (!value) {

            element.textContent =
                "Conference listings";

            return;

        }

        const updated = new Date(value);

        if (Number.isNaN(updated.getTime())) {

            element.textContent =
                "Conference listings";

            return;

        }

        element.textContent =
            "Last updated: " +
            updated.toLocaleDateString("en-US", {
                month: "long",
                day: "numeric",
                year: "numeric",
                timeZone: "America/New_York"
            });

    }


    /* =================================================
       ERROR HANDLING
    ================================================= */

    function renderError(error) {

        console.error(
            "Unable to load conference events:",
            error
        );

        for (const id of [
            "upcoming-events",
            "past-events"
        ]) {

            const container = document.getElementById(id);

            if (!container) {
                continue;
            }

            container.replaceChildren(

                createElement(
                    "div",
                    "news-loading",
                    "Conference listings are temporarily " +
                    "unavailable. Please try again later."
                )

            );

        }

        const updated = document.getElementById(
            "events-updated"
        );

        if (updated) {

            updated.textContent =
                "Unable to load conference listings.";

        }

    }


    /* =================================================
       FETCH EVENTS
    ================================================= */

    async function loadEvents() {

        try {

            const response = await fetch(
                EVENTS_DATA_URL,
                {
                    cache: "no-cache"
                }
            );

            if (!response.ok) {

                throw new Error(
                    `HTTP ${response.status}`
                );

            }

            const data = await response.json();

            if (
                !data ||
                !Array.isArray(data.events)
            ) {

                throw new Error(
                    "Invalid events.json structure."
                );

            }

            const validEvents = data.events.filter(
                validEvent
            );

            const events = deduplicateEvents(
                validEvents
            );

            console.log(
                `Loaded ${events.length} conference events.`
            );

            renderUpcomingEvents(events);

            renderPastEvents(events);

            renderUpdatedTime(data.updated_at);

        } catch (error) {

            renderError(error);

        }

    }


    /* =================================================
       INITIALIZATION
    ================================================= */

    function initializeEvents() {

        const requiredElements = [

            "upcoming-events",
            "upcoming-events-empty",
            "past-events",
            "past-events-empty"

        ];

        if (!requiredElements.every(
            id => document.getElementById(id)
        )) {
            return;
        }

        loadEvents();

    }


    if (document.readyState === "loading") {

        document.addEventListener(
            "DOMContentLoaded",
            initializeEvents
        );

    } else {

        initializeEvents();

    }

})();

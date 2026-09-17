document.addEventListener("DOMContentLoaded", function () {
    const footer = document.getElementById("footer");

    if (!footer) return;

    footer.innerHTML = `
        <footer class="site-footer">

            <div class="footer-main">

                <div class="footer-brand">
                    <h2>DMV PROTON THERAPY<br>COLLABORATIVE</h2>
                    <p>
                        Washington, DC • Maryland • Virginia
                    </p>
                </div>

                <div class="footer-navigation">

                    <div class="footer-links-section">
                        <p class="footer-label">Explore</p>

                        <div class="footer-links">
                            <a href="about.html">About</a>
                            <a href="symposium.html">Symposium</a>
                            <a href="resources.html">Education</a>
                            <a href="news.html">News</a>
                        </div>
                    </div>

                    <div class="footer-contact-section">
                        <p class="footer-label">Contact</p>

                        <a href="mailto:DMVprotonsymposium@gmail.com"
                           class="footer-email">
                            DMVprotonsymposium@gmail.com
                        </a>
                    </div>

                </div>

            </div>

            <div class="footer-bottom">
                <p>
                    © ${new Date().getFullYear()} DMV Proton Therapy Collaborative
                </p>
            </div>

        </footer>
    `;
});

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

                <div class="footer-right">

                    <div class="footer-column footer-explore">
                        <h3>EXPLORE</h3>

                        <div class="footer-links">
                            <a href="about.html">About</a>
                            <a href="symposium.html">Symposium</a>
                            <a href="resources.html">Education</a>
                            <a href="news.html">News</a>
                        </div>
                    </div>

                    <div class="footer-column footer-contact">
                        <h3>CONTACT</h3>
                        <a href="mailto:DMVprotonsymposium@gmail.com">
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

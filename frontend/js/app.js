const statusText = document.querySelector("#api-status");
const statusDot = document.querySelector("#status-dot");

async function checkApiHealth() {
  try {
    const response = await fetch("/api/v1/health", {
      headers: { Accept: "application/json" },
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const body = await response.json();
    if (body.status !== "ok") {
      throw new Error("Unexpected health response");
    }

    statusText.textContent = "FastAPI is healthy.";
    statusDot.classList.add("healthy");
  } catch (error) {
    statusText.textContent = "FastAPI is currently unavailable.";
    statusDot.classList.add("unavailable");
    console.error("Health check failed", error);
  }
}

checkApiHealth();

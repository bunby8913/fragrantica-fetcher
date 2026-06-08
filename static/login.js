const loginButton = document.querySelector("#login-button");
const loginStatus = document.querySelector("#login-status");
const resetLink = document.querySelector("#reset-link");

function setLoginStatus(message, isError = false) {
  loginStatus.textContent = message;
  loginStatus.classList.toggle("error", isError);
}

loginButton.addEventListener("click", async () => {
  loginButton.disabled = true;
  setLoginStatus("Redirecting to Keycloak...");

  try {
    const params = new URLSearchParams(window.location.search);
    await window.Auth.startLogin(params.get("return_to") || "/");
  } catch (error) {
    loginButton.disabled = false;
    setLoginStatus(error.message, true);
  }
});

resetLink.addEventListener("click", (event) => {
  event.preventDefault();
  window.Auth.clearTokens();
  window.location.reload();
});

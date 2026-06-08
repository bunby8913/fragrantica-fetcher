const callbackStatus = document.querySelector("#callback-status");
const retryLink = document.querySelector("#retry-link");

function setCallbackStatus(message, isError = false) {
  callbackStatus.textContent = message;
  callbackStatus.classList.toggle("error", isError);
  if (isError && retryLink) retryLink.style.display = "";
}

(async function () {
  const params = new URLSearchParams(window.location.search);
  const code = params.get("code");
  const error = params.get("error_description") || params.get("error");

  if (error) {
    setCallbackStatus(error, true);
    return;
  }

  if (!code) {
    setCallbackStatus("Missing authorization code. Please try logging in again.", true);
    return;
  }

  try {
    await window.Auth.completeLogin(code);
  } catch (loginError) {
    window.Auth.clearTokens();
    setCallbackStatus(loginError.message, true);
  }
})();

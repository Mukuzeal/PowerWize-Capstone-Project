/* Password visibility toggle, shared by every page with a .pw-wrap field
   (account setup, password reset). The icon reports the current state's
   opposite — an eye offers to reveal, a crossed eye offers to hide. */
function togglePw(id, btn) {
  var input = document.getElementById(id);
  var shown = input.type === 'text';
  input.type = shown ? 'password' : 'text';
  btn.innerHTML = shown
    ? '<i class="fa-solid fa-eye"></i>'
    : '<i class="fa-solid fa-eye-slash"></i>';
  btn.setAttribute('aria-label', shown ? 'Show password' : 'Hide password');
}

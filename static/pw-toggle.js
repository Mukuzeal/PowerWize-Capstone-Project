function togglePw(id, btn) {
  var input = document.getElementById(id);
  var show = input.type === 'password';
  input.type = show ? 'text' : 'password';
  btn.querySelector('i').className = show ? 'fa-solid fa-eye-slash' : 'fa-solid fa-eye';
  btn.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
}

(function(){
  'use strict';

  function initWizard(form){
    var sections = Array.from(form.querySelectorAll(':scope > .section-header'));
    if(sections.length < 2) return;

    // Group each section-header with its immediate-following .form-body into a step.
    var steps = [];
    sections.forEach(function(header, idx){
      var body = header.nextElementSibling;
      if(!body || !body.classList.contains('form-body')) return;
      var titleEl = header.querySelector('h2');
      var title = titleEl ? titleEl.textContent.trim() : ('Step ' + (idx+1));

      var wrap = document.createElement('div');
      wrap.className = 'wizard-step';
      wrap.dataset.stepIndex = String(idx);
      header.parentNode.insertBefore(wrap, header);
      wrap.appendChild(header);
      wrap.appendChild(body);

      steps.push({el: wrap, title: title});
    });
    if(steps.length < 2) return;

    steps[0].el.classList.add('is-current');

    // Build the layout shell around the form.
    var pageBody = form.closest('.page-body');
    var layout = document.createElement('div');
    layout.className = 'wizard-layout';

    var sidebar = document.createElement('aside');
    sidebar.className = 'wizard-sidebar';
    sidebar.innerHTML = '<div class="wizard-sidebar-title">Registration Steps</div>';
    var stepList = document.createElement('ul');
    stepList.className = 'wizard-step-list';
    steps.forEach(function(s, i){
      var li = document.createElement('li');
      li.className = 'wizard-step-item' + (i===0 ? ' is-current' : '');
      li.dataset.targetStep = String(i);
      li.innerHTML = '<span class="wizard-step-num"><span class="wizard-step-num-text">'+(i+1)+'</span></span><span>'+escapeHtml(s.title)+'</span>';
      stepList.appendChild(li);
    });
    sidebar.appendChild(stepList);

    var mobileBar = document.createElement('div');
    mobileBar.className = 'wizard-progress-mobile';
    mobileBar.innerHTML =
      '<div class="wpm-meta"><strong class="wpm-title">'+escapeHtml(steps[0].title)+'</strong><span class="wpm-count">Step 1 of '+steps.length+'</span></div>' +
      '<div class="wpm-bar"><div class="wpm-fill" style="width:'+(100/steps.length)+'%"></div></div>';

    var content = document.createElement('div');
    content.className = 'wizard-content';

    // Move the form into the content column.
    pageBody.parentNode.insertBefore(layout, pageBody);
    layout.appendChild(sidebar);
    layout.appendChild(content);
    content.appendChild(mobileBar);
    // Move every child of pageBody into content (so error banner etc. stay above form)
    while(pageBody.firstChild){ content.appendChild(pageBody.firstChild); }
    pageBody.remove();

    // Replace original submit row with wizard nav.
    var submitBtn = form.querySelector('.form-footer button[type=submit], .form-footer .btn-submit') ||
                    form.querySelector('button[type=submit], .btn-submit');
    var origFooter = submitBtn ? submitBtn.closest('.form-footer') : null;
    if(submitBtn) submitBtn.style.display = 'none';
    if(origFooter) origFooter.style.display = 'none';

    var errBox = document.createElement('div');
    errBox.className = 'wizard-step-error';
    errBox.innerHTML = '<i class="fa-solid fa-circle-exclamation"></i> <span class="wse-msg">Please fill in all required fields before continuing.</span>';
    form.appendChild(errBox);

    var nav = document.createElement('div');
    nav.className = 'wizard-nav';
    nav.innerHTML =
      '<button type="button" class="btn-back" disabled><i class="fa-solid fa-arrow-left"></i> Back</button>' +
      '<span class="step-count">Step <strong class="cur">1</strong> of <strong>'+steps.length+'</strong></span>' +
      '<button type="button" class="btn-next">Next <i class="fa-solid fa-arrow-right"></i></button>';
    form.appendChild(nav);

    var current = 0;
    var btnBack = nav.querySelector('.btn-back');
    var btnNext = nav.querySelector('.btn-next');
    var curEl = nav.querySelector('.cur');

    function setStep(idx){
      if(idx < 0 || idx >= steps.length) return;
      steps[current].el.classList.remove('is-current');
      steps[idx].el.classList.add('is-current');
      current = idx;

      // sidebar markers
      stepList.querySelectorAll('.wizard-step-item').forEach(function(li, i){
        li.classList.remove('is-current','is-done');
        if(i < current) li.classList.add('is-done');
        else if(i === current) li.classList.add('is-current');
      });

      // mobile bar
      mobileBar.querySelector('.wpm-title').textContent = steps[current].title;
      mobileBar.querySelector('.wpm-count').textContent = 'Step '+(current+1)+' of '+steps.length;
      mobileBar.querySelector('.wpm-fill').style.width = ((current+1)/steps.length*100) + '%';

      // nav
      btnBack.disabled = current === 0;
      curEl.textContent = String(current+1);
      if(current === steps.length - 1){
        btnNext.style.display = 'none';
        if(submitBtn){
          submitBtn.style.display = '';
          submitBtn.classList.add('btn-wizard-submit');
          nav.appendChild(submitBtn);
        }
      } else {
        btnNext.style.display = '';
        if(submitBtn) submitBtn.style.display = 'none';
      }

      errBox.classList.remove('show');
      // smooth-scroll to top of form
      var top = form.getBoundingClientRect().top + window.pageYOffset - 12;
      window.scrollTo({top: top, behavior: 'smooth'});
    }

    function validateStep(idx){
      var step = steps[idx].el;
      var fields = step.querySelectorAll('[required]');
      var firstInvalid = null;
      var firstInvalidMsg = null;
      for(var i=0;i<fields.length;i++){
        var f = fields[i];
        // file inputs: required allowed if neither selected nor existing
        if(f.type === 'file'){
          var existingInput = step.querySelector('input[name="'+f.name+'_existing"]');
          var hasExisting = existingInput && existingInput.value;
          var hasFile = f.files && f.files.length > 0;
          if(!hasFile && !hasExisting){ firstInvalid = f; break; }
          // also gate on AI validation status if this field has one
          var valBox = document.getElementById('val-' + f.id);
          if(valBox && hasFile){
            var status = valBox.dataset.status;
            if(status === 'validating'){
              firstInvalid = f;
              firstInvalidMsg = 'Please wait — still validating your upload.';
              break;
            }
            if(status === 'invalid'){
              firstInvalid = f;
              var bad = valBox.querySelector('.uv-bad .uv-msg');
              firstInvalidMsg = bad && bad.textContent ? bad.textContent : 'Please re-upload a valid document.';
              break;
            }
          }
          continue;
        }
        // radio: at least one of the same name checked
        if(f.type === 'radio'){
          var any = step.querySelector('input[name="'+f.name+'"]:checked');
          if(!any){ firstInvalid = f; break; }
          continue;
        }
        if(!f.value || (f.value && f.value.trim && !f.value.trim())){
          firstInvalid = f; break;
        }
      }
      if(firstInvalid){
        var label = firstInvalid.closest('.field');
        var labelText = label && label.querySelector('label') ? label.querySelector('label').textContent.replace(/\s*\*\s*/g,'').replace(/\(.*\)/g,'').trim() : null;
        var title, body;
        if(firstInvalidMsg){
          title = labelText || 'Required field';
          body  = firstInvalidMsg;
        } else {
          title = 'Missing information';
          body  = labelText ? ('Please fill in: ' + labelText) : 'Please fill in all required fields before continuing.';
        }

        if(typeof Swal !== 'undefined'){
          Swal.fire({
            icon: firstInvalidMsg ? 'warning' : 'info',
            title: title,
            text: body,
            confirmButtonColor: '#16583C',
            confirmButtonText: 'OK'
          }).then(function(){
            try { firstInvalid.focus({preventScroll:false}); } catch(e){ firstInvalid.focus(); }
          });
        } else {
          errBox.classList.add('show');
          var msg = errBox.querySelector('.wse-msg');
          if(msg) msg.textContent = body;
          try { firstInvalid.focus({preventScroll:false}); } catch(e){ firstInvalid.focus(); }
        }
        return false;
      }
      // hide any leftover inline error from a prior invalid state
      errBox.classList.remove('show');
      return true;
    }

    btnNext.addEventListener('click', function(){
      if(!validateStep(current)) return;
      setStep(current + 1);
    });
    btnBack.addEventListener('click', function(){
      setStep(current - 1);
    });

    // Pressing Enter inside a step (except in textarea) advances rather than submitting.
    form.addEventListener('keydown', function(e){
      if(e.key !== 'Enter') return;
      if(e.target.tagName === 'TEXTAREA') return;
      if(current < steps.length - 1){
        e.preventDefault();
        if(validateStep(current)) setStep(current + 1);
      }
    });

    // Final submit: run validation across all steps so missed required field doesn't slip through.
    form.addEventListener('submit', function(e){
      for(var i=0;i<steps.length;i++){
        if(!validateStep(i)){
          e.preventDefault();
          setStep(i);
          return;
        }
      }
    });
  }

  function escapeHtml(s){
    return s.replace(/[&<>"']/g, function(c){
      return ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c];
    });
  }

  function boot(){
    document.querySelectorAll('form.form-card[data-wizard]').forEach(initWizard);
  }
  if(document.readyState === 'loading'){
    document.addEventListener('DOMContentLoaded', boot);
  } else { boot(); }
})();

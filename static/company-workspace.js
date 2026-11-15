/* Company batch journey. Secrets and unsaved inputs stay in this DOM only. */
var IK_TAB = 'overview';
var IK_DATA = null;
var IK_REQUEST = 0;

function ikTab(name) {
    IK_TAB = name;
    document.querySelectorAll('[data-ik-tab]').forEach(function (button) {
        button.setAttribute('aria-selected', String(button.dataset.ikTab === name));
        button.tabIndex = button.dataset.ikTab === name ? 0 : -1;
    });
    document.querySelectorAll('[data-ik-section]').forEach(function (section) {
        section.hidden = section.dataset.ikSection !== name;
    });
    var classes=document.getElementById('ik-classes');
    if (name==='training'&&classes&&classes.dataset.loaded!=='yes'&&classes.dataset.loading!=='yes') ikClassesLoad();
}

function ikNext() {
    if (!IK_DATA) return;
    var stage = IK_DATA.summary.stage;
    if (stage === 'roster' || stage === 'review') ikTab('trainees');
    else if (stage === 'registration') {
        ikTab('overview');
        var btn=document.getElementById('ik-send-existing');
        if (btn) ikSendRegistrationLink(null,btn);
    } else ikTab(stage === 'training' ? 'training' : 'billing');
}

function ikNotice(text, ok) {
    var box=document.getElementById('ik-workspace-notice');
    if (!box) return;
    box.className='corp-note '+(ok ? 'corp-note--ok' : 'corp-note--err');
    box.textContent=text;
    box.hidden=false;
}

function _ikRender(d) {
    IK_DATA=d;
    var e=_ikEsc, s=d.summary, b=d.billing;
    var stages={roster:['Add your trainees','Start with the expected roster so missing submissions are visible.','Add trainees'],
        registration:['Registration is open','Send one company invitation. Each trainee uses the shared link, class code and their roster email.','Send registration invitation'],
        review:['Review trainee requirements','Review the application and identity here. Corrections update the same application.','Review trainees'],
        billing:['Prepare company billing','All expected trainees are approved. Account activation can finish independently.','Open billing'],
        payment:['Awaiting company payment','Open the existing invoice to send its link or check payment.','Open billing'],
        training:['Company payment confirmed','Finish account activation, assign the instructor, then trainees join their assigned class.','Open training']};
    var next=stages[s.stage];
    var h='<div class="ik-workspace"><div class="ik-stage" data-ik-live="stage"><div><h3>'+next[0]+'</h3><p>'+next[1]+'</p></div><button class="btn-add" type="button" onclick="ikNext()">'+next[2]+'</button></div>'+
        '<div id="ik-workspace-notice" role="status" aria-live="polite" hidden></div>'+
        '<p id="ik-panel-live-status" class="ik-help" role="status">Live status checks every 5 seconds.</p>'+
        '<nav class="ik-tabs" role="tablist" aria-label="Company batch">';
    [['overview','Overview'],['trainees','Trainees & review'],['billing','Billing'],['training','Training']].forEach(function(t){
        h+='<button type="button" role="tab" data-ik-tab="'+t[0]+'" aria-selected="false" aria-controls="ik-section-'+t[0]+'" onclick="ikTab(\''+t[0]+'\')">'+t[1]+'</button>';
    });
    h+='</nav><section id="ik-section-overview" role="tabpanel" data-ik-section="overview">'+
       '<div class="ik-metrics" data-ik-live="metrics"><div><strong>'+s.total+'</strong><span>Expected trainees</span></div><div><strong>'+s.submitted+' / '+s.total+'</strong><span>Submitted</span></div><div><strong>'+s.approved+' / '+s.total+'</strong><span>Approved</span></div><div><strong>'+s.activated+' / '+s.total+'</strong><span>Accounts activated</span></div></div>'+
       '<p class="ik-help">Approval and account activation are separate. Approved trainees can be invoiced before setting their passwords.</p>'+
       '<h3>Company registration invitation</h3><p>Send the shared registration link and automatically prepared class code to '+e(d.intake.contact_email)+'. Sending again uses the active link.</p>'+
       '<div class="ik-actions"><button id="ik-send-existing" type="button" class="btn-add" onclick="ikSendRegistrationLink(null,this)">Send registration invitation to company</button></div>'+
       '<div id="ik-upload-link-out"></div><div id="ik-registration-send-out" role="status" aria-live="polite"></div>'+
       '<details class="ik-settings"><summary>Manage registration and status links</summary><p class="ik-help">Replace invalidates distributed registration links and unfinished upload sessions. Refreshing does not revoke a link.</p>'+
       '<div class="ik-actions"><button type="button" class="btn-docs" onclick="ikRegistrationLink(this)">'+(d.intake.registration_link_active?'Replace shared registration link':'Generate shared registration link')+'</button>'+
       (d.intake.registration_link_active?'<button type="button" class="btn-docs" onclick="ikRevokeShared(this)">Revoke shared link</button>':'')+
       '<button type="button" class="btn-docs" onclick="ikCoordLink()">'+(d.intake.coord_link_active?'Replace status link':'Generate status link')+'</button>'+
       (d.intake.coord_link_active?'<button type="button" class="btn-docs" onclick="ikRevokeCoordinator(this)">Revoke company link</button>':'')+'</div><div id="ik-coord-link-out"></div></details>'+
       '<details class="ik-settings"><summary>Batch settings'+(d.intake.archived_at?' · Archived':'')+'</summary><p class="ik-help">Archiving moves this intake out of Active. Its roster, links, invoices and classes stay available.</p><button type="button" class="btn-docs" onclick="ikSetArchived('+d.intake.id+','+(!d.intake.archived_at)+',this)">'+(d.intake.archived_at?'Restore to Active':'Archive intake')+'</button><div id="ik-archive-out"></div></details>'+
       '<div data-ik-live="delivery"><h3>Delivery history</h3>'+ikNotices(d.notifications)+
       (d.notifications.some(function(n){return n.status==='in_flight';})?'<button type="button" class="btn-docs" onclick="ikRecoverMail(this)">Check stalled email sends</button>':'')+'</div></section>';
    h+='<section id="ik-section-trainees" role="tabpanel" data-ik-section="trainees" hidden><div data-ik-live="roster"><p><strong>'+s.total+' trainee'+(s.total===1?'':'s')+'</strong> currently on this roster.</p>';
    if (d.slots.length) {
        h+='<div class="table-card ik-roster-scroll"><table><thead><tr><th>Name / email</th><th>Application</th><th>Identity</th><th>Account</th><th>Action</th></tr></thead><tbody>';
        d.slots.forEach(function(r){
            var lab=IK_LABELS[r.status]||[r.status,'badge'];
            h+='<tr><td>'+e(r.full_name)+'<br><span class="ik-help">'+e(r.email)+'</span></td><td><span class="'+lab[1]+'">'+e(r.status_label)+'</span>'+(r.correction?'<p class="ik-help">'+e(r.correction)+'</p>':'')+'</td><td>'+e(r.identity_label)+'</td><td>'+ (r.account_active?'Activated':'Not activated')+'</td><td>'+
                (r.registration?'<button type="button" class="btn-docs" onclick="ikReview(\''+e(r.registration)+'\')">Review requirements</button>':r.invite_revoked?'Access revoked':'Awaiting submission')+'</td></tr>';
        });
        h+='</tbody></table></div>';
    } else h+='<p class="corp-note">No trainees yet. Add the expected names and email addresses below.</p>';
    h+='</div><div id="ik-review-panel"></div><details class="ik-settings"'+(!d.slots.length?' open':'')+'><summary>Add expected trainees</summary><div data-ik-preserve id="ik-roster-draft">'+_ikRosterControls('ik-more')+'<div id="ik-more" oninput="ikUpdateTraineeCount(\'ik-more\')">'+_ikTraineeRow()+'</div><div class="ik-actions"><button type="button" class="btn-docs" onclick="ikAddTrainee(\'ik-more\')">Add another trainee</button><button type="button" class="btn-add" onclick="ikAddSlots()">Add to roster</button></div></div><div id="ik-add-out" role="status"></div></details></section>';
    h+='<section id="ik-section-billing" role="tabpanel" data-ik-section="billing" hidden><div data-ik-live="billing"><h3>Company billing</h3><button type="button" class="btn-docs" onclick="ikCorporateOverview()">All company invoices</button>';
    if (!b.allowed) h+='<p>Billing access is required to manage invoices.</p>';
    else {
        if (!d.eligibility.eligible) {
            h+='<div class="corp-note corp-note--warn"><strong>Not ready for invoicing.</strong> '+e(d.eligibility.reason)+'<ul>';
            ((d.eligibility.detail||{}).outstanding||[]).forEach(function(r){h+='<li>'+e(r.name)+' — '+e(r.label)+'</li>';});
            h+='</ul><button type="button" class="btn-docs" onclick="ikTab(\'trainees\')">Review trainees</button></div>';
        } else h+='<p>All expected trainees are approved. Account activation does not delay billing.</p>';
        if (b.price_blockers.length) h+='<div class="corp-note corp-note--err">No published price: '+e(b.price_blockers.join(', '))+'. Check the registered delivery mode.</div>';
        if (b.coverage_ok===false) h+='<div class="corp-note corp-note--warn">The roster differs from the existing invoice. For a pending invoice, cancel it before preparing a full replacement. A paid invoice stays historical; book additional trainees through a new intake.</div>';
        if (d.eligibility.eligible && b.blockers && b.blockers.length) h+='<ul class="corp-note corp-note--warn">'+b.blockers.map(function(r){return '<li>'+e(r.name)+' ? '+e(r.reason)+'</li>';}).join('')+'</ul>';
        if (b.can_create) h+='<button type="button" class="btn-add" onclick="ikInvoicePreview()">Create corporate invoice</button>';
        b.invoices.forEach(function(i){h+='<article class="ik-invoice-card"><div><strong>'+e(i.reference)+'</strong><p>'+e(i.status)+' · '+_billPeso(i.amount_php)+'</p></div><button type="button" class="btn-docs" onclick="ikOpenInvoice('+i.id+')">Open invoice</button></article>';});
    }
    h+='</div><div id="ik-link-out"></div><div id="ik-billing-detail"></div></section>'+
       '<section id="ik-section-training" role="tabpanel" data-ik-section="training" hidden><h3>Classes and instructor</h3><p class="ik-help">The registration invitation prepares the class automatically. Assign its instructor here. Approved, paid trainees can join from their portal without retyping a code.</p><div id="ik-classes"><div class="empty">Select Training to load classes.</div></div></section></div>';
    return h;
}

function ikNotices(notices) {
    if (!notices.length) return '<p class="ik-help">No delivery attempts yet.</p>';
    var labels={submitted:'Submitted to mail server',queued:'Queued',failed:'Failed',previewed:'Previewed only — NOT emailed',mocked:'Mocked only — NOT emailed',in_flight:'Sending',uncertain:'Outcome unknown'};
    var h='<div class="table-card ik-roster-scroll"><table><thead><tr><th>Notice</th><th>To</th><th>State</th><th>Tries</th><th>Action</th></tr></thead><tbody>';
    notices.forEach(function(n){
        var retry=n.status!=='in_flight'&&(n.status!=='submitted'||n.kind==='registration_link');
        h+='<tr><td>'+_ikEsc(n.slot_name||(n.kind==='registration_link'?'Registration link and class code':n.kind.replace(/_/g,' ')))+'</td><td>'+_ikEsc(n.to_email)+'</td><td>'+_ikEsc(labels[n.status]||n.status)+(n.error?'<p class="ik-help">'+_ikEsc(n.error)+'</p>':'')+'</td><td>'+n.attempts+'</td><td>'+
            (retry?'<button type="button" class="btn-docs" onclick="'+(n.kind==='registration_link'?'ikRetryRegistrationNotice('+n.id+','+(n.status==='uncertain'||n.status==='submitted')+',this)':'ikRetryNotice('+n.id+','+(n.status==='uncertain')+')')+'">'+(n.status==='submitted'?'Resend':'Retry')+'</button>':'')+'</td></tr>';
    });
    return h+'</tbody></table></div><p class="ik-help">Submitted means SMTP accepted the message, not that it reached an inbox.</p>';
}

async function ikReview(regId) {
    ikTab('trainees');
    var id=IK_CURRENT, box=document.getElementById('ik-review-panel');
    box.innerHTML='<p class="corp-note">Loading review…</p>';
    try {
        var response=await fetch('/admin/registration/'+encodeURIComponent(regId)+'/review');
        if (!response.ok) throw new Error('HTTP '+response.status);
        var d=await response.json();
        if (id!==IK_CURRENT||!box.isConnected) return;
        var r=d.registration, e=_ikEsc;
        var h='<article class="table-card" style="padding:1rem;margin:1rem 0" data-review-id="'+e(r.id)+'" data-review-version="'+r.review_version+'"><h3>'+e(r.name)+'</h3><p>'+e(r.email)+' · '+e(r.readiness.display_label)+'</p>'+
            '<div class="ik-review-docs">';
        r.documents.forEach(function(f){h+='<a href="'+e(f.url)+'" target="_blank" rel="noopener">'+e(f.label)+'</a>';});
        h+='</div>'+(r.purged?'<p class="ik-help">Uploads were deleted after final review. Audit outcomes and hashes remain.</p>':'')+
            '<div class="ik-review-grid"><fieldset><legend>Application decision</legend><label><input id="ik-qualified" type="checkbox" '+(r.qualified?'checked':'')+'> Professional qualification met</label><p class="ik-help">Qualification remains separate from identity and permission to train.</p><div class="ik-actions"><button type="button" class="btn-add" onclick="ikReviewAction(\''+r.id+'\',\'accepted\','+r.review_version+',this)">Accept application</button><button type="button" class="btn-docs" onclick="ikReviewAction(\''+r.id+'\',\'rejected\','+r.review_version+',this)">Reject application</button></div></fieldset>'+
            '<fieldset><legend>Identity decision</legend><p>'+e(r.readiness.identity_label)+'</p>';
        if (r.readiness.identity==='pending') h+='<p class="ik-help">Inspect the selfie and identification before deciding.</p><div class="ik-actions"><button type="button" class="btn-add" onclick="ikReviewAction(\''+r.id+'\',\'identity_approved\','+r.review_version+',this)">Approve identity</button><button type="button" class="btn-docs" onclick="ikReviewAction(\''+r.id+'\',\'identity_rejected\','+r.review_version+',this)">Reject identity</button></div>';
        h+='</fieldset></div><form id="ik-correction-form" data-ik-preserve data-review-version="'+r.review_version+'" onsubmit="ikRequestCorrection(event,\''+r.id+'\','+r.review_version+')"><details><summary>Request corrections</summary><p class="ik-help">Select what needs updating. Changes to identification, name or birthdate also require a fresh ID and selfie. The trainee receives a private link to this application; the company receives a status notice.</p><div class="ik-review-grid">';
        d.correction_fields.forEach(function(f){h+='<label><input type="checkbox" name="correction_fields" value="'+e(f.field)+'"> '+e(f.label)+'</label>';});
        h+='</div><label for="ik-correction-note">What needs correcting?</label><textarea class="corp-in" id="ik-correction-note" name="correction_note" maxlength="2000" required>'+e(r.correction_note||'')+'</textarea><div class="ik-actions"><button class="btn-add" type="submit">Request correction and notify</button></div></details></form>'+
            (r.account_linked?'<p class="ik-help">This enrolment is linked to its trainee account. No activation email is needed.</p>':'<div class="ik-actions"><button type="button" class="btn-docs" onclick="ikResendActivation(\''+r.id+'\',this)">Send replacement activation link</button></div>')+
            '<div id="ik-review-notice" role="status" aria-live="polite"></div>';
        if (d.cleanup_pending) h+='<div class="corp-note corp-note--warn">'+d.cleanup_pending+' superseded upload(s) still need cleanup. <button type="button" class="btn-docs" onclick="ikCleanupRetired(\''+r.id+'\',this)">Retry file cleanup</button></div>';
        if (d.notifications.length) h+='<h4>Trainee correction delivery</h4>'+ikNotices(d.notifications);
        if (d.history.length) h+='<details><summary>Review history</summary><ul>'+d.history.map(function(v){return '<li>Review '+v.review_version+' · '+e(v.action.replace(/_/g,' '))+'</li>';}).join('')+'</ul></details>';
        box.innerHTML=h+'</article>';
    } catch(error) {
        if (id===IK_CURRENT) box.innerHTML='<p class="corp-note corp-note--err">Could not load review. <button type="button" class="btn-docs" onclick="ikReview(\''+_ikEsc(regId)+'\')">Retry</button></p>';
    }
}

async function ikReviewSubmit(regId,path,body,button) {
    var intakeId=IK_CURRENT;
    button.disabled=true;
    try {
        var response=await fetch(path,{method:'POST',headers:{'X-CSRFToken':_ikCsrf(),'Accept':'application/json'},body:body});
        var data=await response.json();
        var message=(data.messages||[]).map(function(m){return m.text;}).join(' ')||data.message||data.error||'Check the current review status.';
        if (intakeId!==IK_CURRENT) return;
        if (!response.ok || data.ok===false) { ikNotice(message,false); return; }
        await loadIntake();
        await ikReview(regId);
        ikNotice(message,response.ok&&data.ok!==false);
    } catch(error) {
        if (intakeId===IK_CURRENT) ikNotice('Could not confirm the review outcome. Reload this application before trying again.',false);
    } finally { button.disabled=false; }
}

function ikReviewAction(regId,action,version,button) {
    var body=new FormData(); body.set('review_version',version);
    var path='/admin/registration/'+regId+'/status/'+action;
    if (action.indexOf('identity_')===0) path='/admin/selfie/'+regId+'/'+(action==='identity_approved'?'approve':'reject');
    else body.set('qualified',document.getElementById('ik-qualified').checked?'1':'0');
    ikReviewSubmit(regId,path,body,button);
}

function ikRequestCorrection(event,regId,version) {
    event.preventDefault();
    var body=new FormData(event.target); body.set('review_version',version);
    ikReviewSubmit(regId,'/admin/registration/'+regId+'/status/needs_correction',body,event.target.querySelector('button[type=submit]'));
}

async function ikResendActivation(regId,button) {
    button.disabled=true;
    var result=await hpPost('/admin/registration/'+regId+'/resend-invitation');
    ikNotice(result.data.message||result.data.error||'Could not confirm activation email outcome.',result.ok);
    button.disabled=false;
}

async function ikCleanupRetired(regId,button) {
    button.disabled=true;
    try {
        var result=await hpPost('/admin/registration/'+regId+'/cleanup-retired');
        await ikReview(regId);
        ikNotice(result.data.message||result.data.error||'Could not confirm file cleanup. Check the pending count.',result.ok);
    } finally {button.disabled=false;}
}

async function ikRecoverMail(button) {
    button.disabled=true;
    try {
        var result=await hpPost('/admin/intake/'+IK_CURRENT+'/notifications/recover');
        await loadIntake();
        ikNotice(result.data.message||result.data.error||'Could not confirm recovery. Check delivery history.',result.ok);
    } finally {button.disabled=false;}
}

async function ikRevokeShared(button) {
    if (!confirm('Revoke shared registration access? Unfinished upload sessions will stop working.')) return;
    button.disabled=true;
    try { var result=await hpPost('/admin/intake/'+IK_CURRENT+'/registration-link/revoke'); await loadIntake(); ikNotice(result.ok?'Shared registration link revoked.':'Could not confirm revocation. Reload status before retrying.',result.ok); }
    finally { button.disabled=false; }
}

async function ikRevokeCoordinator(button) {
    button.disabled=true;
    try { var result=await hpPost('/admin/intake/'+IK_CURRENT+'/coordinator-link/revoke'); await loadIntake(); ikNotice(result.ok?'Company status access revoked.':'Could not confirm revocation.',result.ok); }
    finally { button.disabled=false; }
}

document.addEventListener('keydown',function(event){
    if (!event.target.matches('[data-ik-tab]')) return;
    var names=['overview','trainees','billing','training']; var index=names.indexOf(IK_TAB);
    if (event.key==='ArrowRight'||event.key==='ArrowLeft') {
        event.preventDefault(); ikTab(names[(index+(event.key==='ArrowRight'?1:3))%4]);
        document.querySelector('[data-ik-tab="'+IK_TAB+'"]').focus();
    }
});

function ikDeliveryOptions() {
    var program=document.getElementById('ik-program').value;
    var list=[['','Trainees choose their delivery mode'],['Online via Zoom, 7 days','Online via Zoom'],['Hybrid, 5 days online + 2 days face to face at Marvin Plaza, Chino Roces Ave., Makati City, MM','Hybrid'],['Self-paced Online Live Instructors, 3 days','Self-paced online'],['Self-paced Face to Face Instructors, 3 days','Self-paced face to face']];
    if(program!=='training'&&program!=='cea_training') list=[['','Trainees choose their delivery mode'],['Online via Zoom','Online via Zoom'],['Face to Face','Face to face']];
    document.getElementById('ik-delivery').innerHTML=list.map(function(o){return '<option value="'+_ikEsc(o[0])+'">'+_ikEsc(o[1])+'</option>';}).join('');
}

function ikCorporateOverview() {
    // hpGoToCorporate() -> showSection('corporate') already calls
    // hpQueueLoad(); a second call here raced it, and whichever fetch
    // resolved last overwrote #hp-queue mid-interaction.
    closeIntake();hpGoToCorporate();
}

/* Read-only live updates. Patch status regions, never the surrounding forms,
   one-time link boxes, review drafts, selected tab or modal scroll position. */
var IK_LIVE_TIMER = null;
var IK_LIVE_INFLIGHT = null;
var IK_LIVE_FAILURES = 0;
var IK_LIVE_STOPPED = false;

function ikLiveVisible() {
    var section=document.getElementById('section-intake');
    return !document.hidden && section && section.classList.contains('active');
}

function ikLiveEditing(root) {
    var active=document.activeElement;
    return root && root.contains(active) && active.matches('input,textarea,select,[contenteditable="true"]');
}

function ikLiveReplace(node, html) {
    if (node.innerHTML===html) return true;
    if (ikLiveEditing(node)) return false;
    var active=document.activeElement;
    var action=node.contains(active)&&active.tagName==='BUTTON'?active.getAttribute('onclick'):null;
    node.innerHTML=html;
    if (action) {
        var replacement=Array.from(node.querySelectorAll('button')).find(function(button){return button.getAttribute('onclick')===action;});
        if (replacement) replacement.focus({preventScroll:true});
    }
    return true;
}

function ikLiveStatus(message) {
    ['ik-live-status','ik-panel-live-status'].forEach(function(id){var node=document.getElementById(id);if(node) node.textContent=message;});
}

async function ikLiveJson(url) {
    var controller=new AbortController();
    var timer=setTimeout(function(){controller.abort();},10000);
    try {
        var response=await fetch(url,{cache:'no-store',signal:controller.signal,headers:{Accept:'application/json'}});
        if (response.redirected || response.status===401 || response.status===403) {
            var denied=new Error('Session ended or access changed. Sign in again to resume live updates.');
            denied.accessDenied=true;throw denied;
        }
        if (!response.ok) throw new Error('HTTP '+response.status);
        return await response.json();
    } finally {clearTimeout(timer);}
}

function ikLiveList(records) {
    var table=document.getElementById('ik-intake-table'), empty=document.getElementById('ik-empty-row');
    if (!table || table.querySelector('button:disabled')) return;
    var body=table.tBodies[0], existing=new Map(), seen=new Set(), anchor=body.firstElementChild;
    body.querySelectorAll('tr[data-intake-id]').forEach(function(row){existing.set(Number(row.dataset.intakeId),row);});
    records.forEach(function(record){
        var id=Number(record.id);
        if (!Number.isInteger(id) || id<1) return;
        seen.add(id);
        var row=existing.get(id), signature=JSON.stringify(record), e=_ikEsc;
        if (!row) {row=document.createElement('tr');row.dataset.intakeId=id;}
        if (row.dataset.liveSignature!==signature) {
            var badge=['b-accepted','b-pending','b-rejected'].indexOf(record.status_class)>=0?record.status_class:'b-pending';
            row.dataset.archived=String(record.archived);
            ikLiveReplace(row,'<td><strong>'+e(record.company_name)+'</strong></td><td>'+e(record.program_label)+'</td>'+
                '<td>'+e(record.contact_person)+'<br><span class="ik-help">'+e(record.contact_email)+'</span></td>'+
                '<td>'+record.submitted_count+' / '+record.slot_count+' submitted</td><td>'+
                '<span class="badge" data-ik-archive-badge'+(record.archived?'':' style="display:none"')+'>Archived</span> '+
                '<span class="badge '+badge+'">'+e(record.display_status)+'</span></td>'+
                '<td style="text-align:right"><button type="button" class="btn-docs" onclick="openIntake('+id+')">Manage</button> '+
                '<button type="button" class="btn-docs" data-ik-archive-action onclick="ikSetArchived('+id+','+(!record.archived)+',this)">'+(record.archived?'Restore':'Archive')+'</button></td>');
            row.dataset.liveSignature=signature;
        }
        if (row===anchor) anchor=anchor.nextElementSibling;
        else body.insertBefore(row,anchor||empty);
    });
    existing.forEach(function(row,id){if (!seen.has(id)) row.remove();});
    ikFilterIntakes(IK_LIST_VIEW);
}

function ikLivePanel(data) {
    var mount=document.getElementById('intake-body');
    if (!mount || !mount.querySelector('.ik-workspace') || mount.querySelector('button:disabled')) return;
    var previous=IK_DATA;
    var scratch=document.createElement('div');scratch.innerHTML=_ikRender(data);
    scratch.querySelectorAll('[data-ik-live]').forEach(function(next){
        var current=mount.querySelector('[data-ik-live="'+next.dataset.ikLive+'"]');
        if (!current) return;
        ikLiveReplace(current,next.innerHTML);
    });
    document.getElementById('intake-title').textContent=data.intake.company_name;
    document.getElementById('intake-sub').textContent=data.intake.program_label+' - '+data.intake.contact_person+' - '+data.intake.contact_email;
    var review=mount.querySelector('[data-review-id]');
    if (review && previous) {
        var oldSlot=previous.slots.find(function(s){return s.registration===review.dataset.reviewId;});
        var newSlot=data.slots.find(function(s){return s.registration===review.dataset.reviewId;});
        if (JSON.stringify(oldSlot)!==JSON.stringify(newSlot)) {
            var note=document.getElementById('ik-review-live-notice');
            if (!note) {note=document.createElement('p');note.id='ik-review-live-notice';note.className='corp-note corp-note--warn';review.prepend(note);}
            note.textContent='This trainee\u2019s status changed. Your draft is preserved. Open Review requirements again before making another decision.';
        }
    }
}

async function ikLiveClasses(intakeId) {
    var box=document.getElementById('ik-classes');
    if (!box || box.dataset.loading==='yes' || ikLiveEditing(box) || box.querySelector('button:disabled') || box.querySelector('[data-loading="yes"]')) return;
    var revision=box.dataset.revision;
    var data=await ikLiveJson('/admin/intake/'+intakeId+'/classes');
    if (IK_CURRENT!==intakeId || !box.isConnected || box.dataset.revision!==revision || IK_TAB!=='training' || !ikLiveVisible()) return;
    var signature=JSON.stringify(data);
    var open=Array.from(box.querySelectorAll('[data-live-class-open="yes"]'));
    if (box.dataset.liveSignature!==signature) {
        var focused=document.activeElement, action=box.contains(focused)?focused.getAttribute('onclick'):null;
        box.innerHTML=_ikClassesRender(data.classes||[],data.instructors||[]);
        open.forEach(function(slot){var next=document.getElementById(slot.id);if(next) next.replaceWith(slot);});
        if (focused.isConnected && box.contains(focused)) focused.focus({preventScroll:true});
        else if(action) {
            var replacement=Array.from(box.querySelectorAll('button')).find(function(button){return button.getAttribute('onclick')===action;});
            if(replacement) replacement.focus({preventScroll:true});
        }
        box.dataset.liveSignature=signature;box.dataset.loaded='yes';
    }
    await Promise.all(open.filter(function(slot){return slot.isConnected;}).map(function(slot){
        return ikClassPanel(Number(slot.id.replace('ik-cls-','')),{background:true});
    }));
}

async function ikLiveRun() {
    try {
        var records=await ikLiveJson('/admin/intake/list');
        if (!ikLiveVisible()) return;
        ikLiveList(records.records);
        var intakeId=IK_CURRENT, revision=IK_REQUEST;
        if (intakeId && document.getElementById('intake-overlay').classList.contains('open')) {
            var panel=await ikLiveJson('/admin/intake/'+intakeId+'/panel');
            if (IK_CURRENT!==intakeId || IK_REQUEST!==revision || !ikLiveVisible()) return;
            ikLivePanel(panel);
            if (IK_TAB==='training') await ikLiveClasses(intakeId);
            if (IK_TAB==='billing' && HP_CID) await hpLoad({background:true});
        }
        IK_LIVE_FAILURES=0;
        ikLiveStatus('Live updates on \u00b7 checked '+new Date().toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'}));
    } catch(error) {
        IK_LIVE_FAILURES++;
        if (error.accessDenied) IK_LIVE_STOPPED=true;
        ikLiveStatus(error.accessDenied?error.message:'Live updates interrupted. Showing the last known status; retrying automatically.');
    }
}

function ikLiveRefresh() {
    if (IK_LIVE_INFLIGHT) return IK_LIVE_INFLIGHT;
    if (IK_LIVE_STOPPED || !ikLiveVisible()) return Promise.resolve();
    clearTimeout(IK_LIVE_TIMER);
    IK_LIVE_INFLIGHT=ikLiveRun().finally(function(){
        IK_LIVE_INFLIGHT=null;
        IK_LIVE_TIMER=setTimeout(ikLiveRefresh,Math.min(30000,5000*Math.pow(2,IK_LIVE_FAILURES)));
    });
    return IK_LIVE_INFLIGHT;
}

document.addEventListener('visibilitychange',function(){
    if (document.hidden) clearTimeout(IK_LIVE_TIMER);
    else ikLiveRefresh();
});
window.addEventListener('focus',ikLiveRefresh);
document.addEventListener('DOMContentLoaded',ikLiveRefresh);

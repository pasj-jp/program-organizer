const board = document.querySelector('.board');
const sessionsScroll = document.getElementById('sessions-scroll');
const sessionsTrack = document.getElementById('sessions-track');
const topScroll = document.getElementById('board-scroll-top');
const topScrollSpacer = document.getElementById('board-scroll-spacer');
function updateTopScroll(){
  const overflowing=sessionsScroll.scrollWidth>sessionsScroll.clientWidth+1;
  topScroll.hidden=!overflowing;
  sessionsScroll.classList.toggle('top-scroll-ready',overflowing);
  if(overflowing){
    topScrollSpacer.style.width=`${sessionsScroll.scrollWidth}px`;
    topScroll.scrollLeft=sessionsScroll.scrollLeft;
  }
}
topScroll.addEventListener('scroll',()=>{
  if(sessionsScroll.scrollLeft!==topScroll.scrollLeft)sessionsScroll.scrollLeft=topScroll.scrollLeft;
});
sessionsScroll.addEventListener('scroll',()=>{
  if(topScroll.scrollLeft!==sessionsScroll.scrollLeft)topScroll.scrollLeft=sessionsScroll.scrollLeft;
});
window.addEventListener('resize',updateTopScroll);
if('ResizeObserver' in window)new ResizeObserver(updateTopScroll).observe(sessionsScroll);
requestAnimationFrame(updateTopScroll);
const canChange = board.dataset.canChange === 'true';
const formatFilter = document.getElementById('format-filter');
const categoryFilter = document.getElementById('category-filter');
const feedback = document.getElementById('feedback');
let dragged = null;
let source = null;
let highlightedList = null;
function highlightList(list){
  if(highlightedList===list)return;
  if(highlightedList)highlightedList.classList.remove('over');
  highlightedList=list;
  if(list)list.classList.add('over');
}
function notice(message, error=false){feedback.textContent=message;feedback.classList.toggle('error',error);feedback.hidden=false;}
document.querySelectorAll('[data-open-dialog]').forEach(button=>{
  button.addEventListener('click',()=>{
    const dialog=document.getElementById(button.dataset.openDialog);
    dialog.showModal();
    dialog.querySelector('input:not([type="hidden"]), select')?.focus();
  });
});
document.querySelectorAll('.action-dialog').forEach(dialog=>{
  dialog.querySelector('.dialog-cancel')?.addEventListener('click',()=>dialog.close());
  if(dialog.dataset.openOnError==='true'){
    dialog.showModal();
    dialog.querySelector('.errorlist')?.scrollIntoView({block:'nearest'});
  }
});
document.getElementById('program-export-form')?.addEventListener('submit',event=>{
  const form=event.currentTarget;
  form.action=form.querySelector('input[name="format"]:checked').dataset.downloadUrl;
  form.closest('dialog').close();
});
function refreshCounts(){document.querySelectorAll('.column').forEach(col=>col.querySelector('.count').textContent=col.querySelectorAll('.card').length);}
function applyFilter(){
  const format=formatFilter.value;
  const category=categoryFilter.value;
  document.querySelectorAll('.unassigned .card').forEach(card=>{
    const formatMatches=!format||card.dataset.format===format.slice(7);
    const categoryMatches=!category||card.dataset.categoryFirst===category||card.dataset.categorySecond===category;
    card.hidden=!(formatMatches&&categoryMatches);
  });
}
formatFilter.addEventListener('change',applyFilter);
categoryFilter.addEventListener('change',applyFilter);
function initializeEditDialog({name, openError, saveError, focusSelector, initializeContent = () => {}}) {
  const dialog = document.getElementById(`${name}-dialog`);
  const content = document.getElementById(`${name}-dialog-content`);
  async function replaceContent(response) {
    content.innerHTML = await response.text();
    initializeContent(content);
  }
  board.addEventListener('click', async event => {
    const button = event.target.closest(`.edit-${name}`);
    if (!button) return;
    try {
      const response = await fetch(button.dataset.editUrl);
      if (!response.ok) throw new Error(openError);
      await replaceContent(response);
      dialog.showModal();
      dialog.querySelector(focusSelector)?.focus();
    } catch (error) {
      notice(error.message, true);
    }
  });
  dialog.addEventListener('click', event => {
    if (event.target.closest('.dialog-cancel')) dialog.close();
  });
  dialog.addEventListener('submit', async event => {
    if (event.target.id !== `${name}-edit-form`) return;
    event.preventDefault();
    const form = event.target;
    const submit = form.querySelector('button[type="submit"]');
    submit.disabled = true;
    try {
      const response = await fetch(form.action, {method: 'POST', body: new FormData(form)});
      if (response.status === 400) {
        await replaceContent(response);
        dialog.querySelector('.errorlist')?.scrollIntoView({block: 'nearest'});
        return;
      }
      if (!response.ok) throw new Error(saveError);
      location.reload();
    } catch (error) {
      notice(error.message, true);
      dialog.close();
    } finally {
      submit.disabled = false;
    }
  });
}
initializeEditDialog({
  name: 'presentation',
  openError: '編集画面を開けませんでした。',
  saveError: '演題を保存できませんでした。',
  focusSelector: 'textarea, input, select',
});
initializeEditDialog({
  name: 'session',
  openError: 'セッションの編集画面を開けませんでした。',
  saveError: 'セッションを保存できませんでした。',
  focusSelector: 'input:not([type=hidden])',
  initializeContent: initializeSessionKind,
});
if(canChange){
  document.querySelectorAll('.card').forEach(card=>{
    if(card.dataset.status==='withdrawn')return;
    card.draggable=true;
    card.addEventListener('dragstart',event=>{dragged=card;source=card.parentElement;card.classList.add('dragging');event.dataTransfer.effectAllowed='move';event.dataTransfer.setData('text/plain',card.dataset.id);});
    card.addEventListener('dragend',()=>{card.classList.remove('dragging');highlightList(null);});
  });
  document.querySelectorAll('.cards').forEach(list=>{
    list.addEventListener('dragover',event=>{if(!dragged)return;event.preventDefault();highlightList(list);const next=[...list.querySelectorAll('.card:not(.dragging):not([hidden])')].find(card=>event.clientY<card.getBoundingClientRect().top+card.offsetHeight/2);list.insertBefore(dragged,next||null);});
    list.addEventListener('drop',async event=>{
      event.preventDefault();
      highlightList(null);
      if(!dragged)return;
      const card=dragged;
      const original=source;
      const target=list;
      const order=[...target.querySelectorAll('.card')].map(c=>Number(c.dataset.id));
      const token=document.cookie.split('; ').find(x=>x.startsWith('csrftoken='))?.split('=')[1];
      try{
        const response=await fetch(board.dataset.moveUrl,{method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':decodeURIComponent(token||'')},body:JSON.stringify({presentation_id:Number(card.dataset.id),session_id:target.dataset.session||null,meeting_id:board.dataset.meetingId||null,order})});
        const result=await response.json();
        if(!response.ok)throw new Error(result.error||'保存できませんでした。');
        card.hidden=false;
        card.querySelector('.category-details').hidden=Boolean(target.dataset.session);
        card.querySelector('.assigned-category').hidden=!target.dataset.session;
        card.querySelector('.category-value').textContent=result.confirmed_category||'未設定';
        applyFilter();
        refreshCounts();
        for (const [id, endTime] of Object.entries(result.end_times || {})) {
          const label = document.querySelector(`.end-time[data-session="${id}"]`);
          if (label) label.textContent = endTime ? `–${endTime}` : '';
        }
        for (const [id, data] of Object.entries(result.program_numbers || {})) {
          const updatedCard = document.querySelector(`.card[data-id="${id}"]`);
          if (!updatedCard) continue;
          updatedCard.querySelector('.program-number').textContent = data.number || data.submission;
        }
        notice('割り当てを保存しました。');
      }catch(error){notice(error.message+' 画面を再読み込みします。',true);setTimeout(()=>location.reload(),900);}
      dragged=null;source=null;
    });
  });
}
if(board.dataset.canReorderSessions === 'true' && board.dataset.reorderUrl){
  let draggedSession = null;
  let originalOrder = [];
  let dropped = false;
  let scrollTimer = null;
  let scrollSpeed = 0;
  let pointerX = 0;
  let pointerY = 0;
  function stopAutoScroll(){
    if(scrollTimer)clearInterval(scrollTimer);
    scrollTimer=null;
    scrollSpeed=0;
  }
  function positionSession(clientX,clientY){
    const target=document.elementFromPoint(clientX,clientY)?.closest('.session-column');
    if(!target||!sessionsTrack.contains(target)||target===draggedSession)return;
    const before=clientX<target.getBoundingClientRect().left+target.offsetWidth/2;
    const next=before?target:target.nextElementSibling;
    if(draggedSession.nextElementSibling!==next)sessionsTrack.insertBefore(draggedSession,next);
  }
  function updateAutoScroll(event){
    pointerX=event.clientX;
    pointerY=event.clientY;
    const rect=sessionsScroll.getBoundingClientRect();
    const edge=65;
    if(pointerY<rect.top||pointerY>rect.bottom||pointerX<rect.left-40||pointerX>rect.right+40){
      stopAutoScroll();
      return;
    }
    const left=Math.max(0,pointerX-rect.left);
    const right=Math.max(0,rect.right-pointerX);
    scrollSpeed=left<edge?-Math.max(4,Math.round((edge-left)/edge*18)):
      right<edge?Math.max(4,Math.round((edge-right)/edge*18)):0;
    if(!scrollSpeed){stopAutoScroll();return;}
    if(scrollTimer)return;
    scrollTimer=setInterval(()=>{
      if(!draggedSession){stopAutoScroll();return;}
      sessionsScroll.scrollLeft+=scrollSpeed;
      positionSession(pointerX,pointerY);
    },16);
  }
  const sessionColumns = [...sessionsTrack.querySelectorAll('.session-column')];
  sessionColumns.forEach(column=>{
    const handle = column.querySelector('.session-handle');
    handle.addEventListener('dragstart',event=>{
      draggedSession=column;
      originalOrder=[...sessionsTrack.querySelectorAll('.session-column')];
      dropped=false;
      column.classList.add('session-dragging');
      event.dataTransfer.effectAllowed='move';
      event.dataTransfer.setData('text/plain',`session:${column.dataset.sessionId}`);
    });
    handle.addEventListener('dragend',()=>{
      stopAutoScroll();
      column.classList.remove('session-dragging');
      if(!dropped)originalOrder.forEach(item=>sessionsTrack.appendChild(item));
      draggedSession=null;
    });
    column.addEventListener('dragover',event=>{
      if(!draggedSession)return;
      event.preventDefault();
      event.stopPropagation();
      updateAutoScroll(event);
      positionSession(event.clientX,event.clientY);
    });
  });
  sessionsScroll.addEventListener('dragover',event=>{
    if(!draggedSession)return;
    event.preventDefault();
    updateAutoScroll(event);
    positionSession(event.clientX,event.clientY);
  });
  document.addEventListener('dragover',event=>{
    if(draggedSession)updateAutoScroll(event);
  });
  sessionsScroll.addEventListener('drop',async event=>{
    if(!draggedSession)return;
    event.preventDefault();
    stopAutoScroll();
    dropped=true;
    const order=[...sessionsTrack.querySelectorAll('.session-column')].map(column=>Number(column.dataset.sessionId));
    const token=document.cookie.split('; ').find(value=>value.startsWith('csrftoken='))?.split('=')[1];
    try{
      const response=await fetch(board.dataset.reorderUrl,{method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':decodeURIComponent(token||'')},body:JSON.stringify({order})});
      const result=await response.json();
      if(!response.ok)throw new Error(result.error||'セッションの順序を保存できませんでした。');
      notice('セッションの順序を保存しました。');
    }catch(error){notice(error.message+' 画面を再読み込みします。',true);setTimeout(()=>location.reload(),900);}
  });
}

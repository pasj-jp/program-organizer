const board = document.querySelector('.board');
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
const presentationDialog = document.getElementById('presentation-dialog');
const presentationDialogContent = document.getElementById('presentation-dialog-content');
board.addEventListener('click',async event=>{
  const button=event.target.closest('.edit-presentation');
  if(!button)return;
  try{
    const response=await fetch(button.dataset.editUrl);
    if(!response.ok)throw new Error('編集画面を開けませんでした。');
    presentationDialogContent.innerHTML=await response.text();
    presentationDialog.showModal();
    presentationDialog.querySelector('textarea, input, select')?.focus();
  }catch(error){notice(error.message,true);}
});
presentationDialog.addEventListener('click',event=>{
  if(event.target.closest('.dialog-cancel'))presentationDialog.close();
});
presentationDialog.addEventListener('submit',async event=>{
  if(event.target.id!=='presentation-edit-form')return;
  event.preventDefault();
  const form=event.target;
  const submit=form.querySelector('button[type="submit"]');
  submit.disabled=true;
  try{
    const response=await fetch(form.action,{method:'POST',body:new FormData(form)});
    if(response.status===400){
      presentationDialogContent.innerHTML=await response.text();
      presentationDialog.querySelector('.errorlist')?.scrollIntoView({block:'nearest'});
      return;
    }
    if(!response.ok)throw new Error('演題を保存できませんでした。');
    location.reload();
  }catch(error){notice(error.message,true);presentationDialog.close();}
  finally{submit.disabled=false;}
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
        const response=await fetch(board.dataset.moveUrl,{method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':decodeURIComponent(token||'')},body:JSON.stringify({presentation_id:Number(card.dataset.id),session_id:target.dataset.session||null,order})});
        const result=await response.json();
        if(!response.ok)throw new Error(result.error||'保存できませんでした。');
        card.hidden=false;
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
  const sessionColumns = [...board.querySelectorAll('.session-column')];
  sessionColumns.forEach(column=>{
    const handle = column.querySelector('.session-handle');
    handle.addEventListener('dragstart',event=>{
      draggedSession=column;
      originalOrder=[...board.querySelectorAll('.session-column')];
      dropped=false;
      column.classList.add('session-dragging');
      event.dataTransfer.effectAllowed='move';
      event.dataTransfer.setData('text/plain',`session:${column.dataset.sessionId}`);
    });
    handle.addEventListener('dragend',()=>{
      column.classList.remove('session-dragging');
      if(!dropped)originalOrder.forEach(item=>board.appendChild(item));
      draggedSession=null;
    });
    column.addEventListener('dragover',event=>{
      if(!draggedSession)return;
      event.preventDefault();
      event.stopPropagation();
      if(column===draggedSession)return;
      const before=event.clientX < column.getBoundingClientRect().left + column.offsetWidth/2;
      const next=before ? column : column.nextElementSibling;
      if(draggedSession.nextElementSibling!==next)board.insertBefore(draggedSession,next);
    });
  });
  board.addEventListener('dragover',event=>{if(draggedSession)event.preventDefault();});
  board.addEventListener('drop',async event=>{
    if(!draggedSession)return;
    event.preventDefault();
    dropped=true;
    const order=[...board.querySelectorAll('.session-column')].map(column=>Number(column.dataset.sessionId));
    const token=document.cookie.split('; ').find(value=>value.startsWith('csrftoken='))?.split('=')[1];
    try{
      const response=await fetch(board.dataset.reorderUrl,{method:'POST',headers:{'Content-Type':'application/json','X-CSRFToken':decodeURIComponent(token||'')},body:JSON.stringify({order})});
      const result=await response.json();
      if(!response.ok)throw new Error(result.error||'セッションの順序を保存できませんでした。');
      notice('セッションの順序を保存しました。');
    }catch(error){notice(error.message+' 画面を再読み込みします。',true);setTimeout(()=>location.reload(),900);}
  });
}

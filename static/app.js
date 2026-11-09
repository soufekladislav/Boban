(() => {
  const sidebar = document.querySelector('[data-sidebar]');
  const backdrop = document.querySelector('[data-sidebar-backdrop]');
  const openSidebar = () => { sidebar?.classList.add('open'); backdrop?.classList.add('open'); document.body.classList.add('sidebar-open'); };
  const closeSidebar = () => { sidebar?.classList.remove('open'); backdrop?.classList.remove('open'); document.body.classList.remove('sidebar-open'); };
  document.querySelectorAll('[data-sidebar-open]').forEach(btn => btn.addEventListener('click', openSidebar));
  document.querySelectorAll('[data-sidebar-close]').forEach(btn => btn.addEventListener('click', closeSidebar));
  backdrop?.addEventListener('click', closeSidebar);
  document.addEventListener('keydown', ev => { if (ev.key === 'Escape') { closeSidebar(); if (panel) panel.hidden = true; } });

  function rowChecksForForm(form) {
    if (!form) return [];
    return Array.from(form.elements || []).filter(el => el.classList && el.classList.contains('js-row-check'));
  }

  function updateSelectedCount(form) {
    if (!form) return;
    const rows = rowChecksForForm(form);
    const count = rows.filter(el => el.checked).length;
    document.querySelectorAll(`.js-select-all[data-select-all="#${form.id}"]`).forEach(el => {
      el.checked = rows.length > 0 && count === rows.length;
      el.indeterminate = count > 0 && count < rows.length;
    });
    document.querySelectorAll(`[data-selected-count][data-form="#${form.id}"]`).forEach(el => { el.textContent = count; });
    form.querySelectorAll('[data-selected-count]').forEach(el => { el.textContent = count; });
  }

  document.querySelectorAll('.js-select-all').forEach(master => {
    master.addEventListener('change', () => {
      const selector = master.getAttribute('data-select-all');
      const form = selector ? document.querySelector(selector) : master.closest('form');
      if (!form) return;
      rowChecksForForm(form).forEach(cb => { cb.checked = master.checked; });
      updateSelectedCount(form);
    });
  });
  document.querySelectorAll('form').forEach(form => {
    const rows = rowChecksForForm(form);
    if (!rows.length) return;
    rows.forEach(cb => cb.addEventListener('change', () => updateSelectedCount(form)));
    updateSelectedCount(form);
  });

  // Chat: keep the latest exchange in view and submit without reloading the page.
  function chatEscape(value) {
    return String(value ?? '').replace(/[&<>'"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
  }
  function chatScrollBottom(log, smooth=false) {
    if (!log) return;
    window.requestAnimationFrame(() => {
      log.scrollTo({top: log.scrollHeight, behavior: smooth ? 'smooth' : 'auto'});
    });
  }
  function chatActionsHtml(actions) {
    if (!Array.isArray(actions) || !actions.length) return '';
    return `<div class="chat-actions">${actions.map(a => `<a class="btn small-btn ${a.primary ? 'primary' : ''}" href="${chatEscape(a.url || '#')}">${chatEscape(a.label || 'Otevřít')}</a>`).join('')}</div>`;
  }
  // Safe, deliberately small rich-text renderer. No raw HTML from the model is trusted.
  function visibleChatText(value) {
    if (typeof value !== 'string') return String(value ?? '');
    let text=value.trim();
    for (let n=0;n<3;n++) {
      let candidate=text;
      if (/^```(?:json)?\s*\n/i.test(candidate) && /```\s*$/.test(candidate)) candidate=candidate.replace(/^```(?:json)?\s*\n/i,'').replace(/```\s*$/,'').trim();
      if (!candidate.startsWith('{')) break;
      try {const result=JSON.parse(candidate);if (!result || typeof result!=='object' || Array.isArray(result)) break;
        const next=result.answer??result.text??result.message??result.content;
        if(typeof next!=='string')break;text=next.trim();
      }catch(_){break;}
    }
    return text;
  }
  function chatClock(raw) {
    if (!raw) return '';
    // The server currently writes local ISO timestamps without UTC offset: preserve that wall time.
    const hit=String(raw).match(/^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/);
    return hit?`${hit[3]}.${hit[2]}.${hit[1]} ${hit[4]}:${hit[5]}`:String(raw);
  }
  function chatTimeElement(raw) {
    const time=document.createElement('time'); time.className='chat-message-time';
    const iso=raw||new Date().toISOString();time.dateTime=iso;
    time.textContent=raw?chatClock(raw):new Intl.DateTimeFormat('cs-CZ',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}).format(new Date());
    return time;
  }
  function richChat(value) {
    const safeUrl = raw => { try { const u=new URL(raw,location.origin); return ['https:','http:'].includes(u.protocol) ? u.href : null; } catch { return null; } };
    const inline = raw => chatEscape(raw).replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>').replace(/`([^`]+)`/g,'<code>$1</code>').replace(/\[([^\]]+)\]\(([^)]+)\)/g,(_,title,rawUrl)=> {const url=safeUrl(rawUrl.replaceAll('&amp;','&'));return url ? `<a href="${chatEscape(url)}" target="_blank" rel="noopener noreferrer">${title}</a>` : title;});
    const lines=String(value??'').split(/\r?\n/), out=[];
    let i=0;
    while(i<lines.length){const line=lines[i];
      if(/^\|.+\|$/.test(line) && i+1<lines.length && /^\|?[\s:|-]+\|?$/.test(lines[i+1])){
        const cells=v=>v.replace(/^\||\|$/g,'').split('|').map(x=>x.trim());
        out.push('<table><thead><tr>'+cells(line).map(x=>'<th>'+inline(x)+'</th>').join('')+'</tr></thead><tbody>');i+=2;
        while(i<lines.length && /^\|.+\|$/.test(lines[i])){out.push('<tr>'+cells(lines[i]).map(x=>'<td>'+inline(x)+'</td>').join('')+'</tr>');i++;}
        out.push('</tbody></table>');continue;
      }
      if(/^\s*[-*]\s+/.test(line)){out.push('<ul>');while(i<lines.length && /^\s*[-*]\s+/.test(lines[i])){out.push('<li>'+inline(lines[i].replace(/^\s*[-*]\s+/,''))+'</li>');i++;}out.push('</ul>');continue;}
      if(!line.trim()){i++;continue;}
      const heading=line.match(/^(#{1,3})\s+(.+)$/);
      if(heading){const level=heading[1].length+1;out.push(`<h${level}>${inline(heading[2])}</h${level}>`);i++;continue;}
      if(/^\s*\d+[.)]\s+/.test(line)){out.push('<ol>');while(i<lines.length && /^\s*\d+[.)]\s+/.test(lines[i])){out.push('<li>'+inline(lines[i].replace(/^\s*\d+[.)]\s+/,''))+'</li>');i++;}out.push('</ol>');continue;}
      if(/^>\s?/.test(line)){out.push('<blockquote>');while(i<lines.length && /^>\s?/.test(lines[i])){out.push('<p>'+inline(lines[i].replace(/^>\s?/,''))+'</p>');i++;}out.push('</blockquote>');continue;}
      if(/^```/.test(line)){const code=[];i++;while(i<lines.length && !/^```/.test(lines[i])){code.push(lines[i]);i++;}out.push('<pre><code>'+chatEscape(code.join('\n'))+'</code></pre>');if(i<lines.length)i++;continue;}
      if(/^---+$/.test(line.trim())){out.push('<hr>');i++;continue;}
      out.push('<p>'+inline(line)+'</p>');i++;
    }
    return out.join('');
  }
  function renderAssistantBubble(el, text) {
    const raw = visibleChatText(text);
    if (raw.length > 2700) {
      const parts = raw.split(/\n\s*\n/);
      if (parts.length > 3) {
        const first = []; let used = 0; let at = 0;
        for (const p of parts) {
          if (used + p.length > 1200 && first.length) break;
          first.push(p); used += p.length; at++;
        }
        if (at < parts.length) {
          el.innerHTML = richChat(first.join('\n\n')) +
            '<details class="chat-long-answer"><summary>Zobrazit pokračování odpovědi</summary>' +
            richChat(parts.slice(at).join('\n\n')) + '</details>';
          return;
        }
      }
    }
    el.innerHTML = richChat(raw);
  }
  document.querySelectorAll('[data-rich-chat]').forEach(el=>{renderAssistantBubble(el,el.textContent);});
  document.querySelectorAll('[data-chat-created-at]').forEach(el=>{el.textContent=chatClock(el.dataset.chatCreatedAt);});
  document.querySelectorAll('[data-project-picker]').forEach(el=>el.addEventListener('change',()=>{if(el.value) location.href=el.value;}));
  function appendChatMessage(log, role, body, actions=[], createdAt=null) {
    if (!log) return null;
    const end = log.querySelector('[data-chat-end]');
    const wrap = document.createElement('div');
    wrap.className = `message-wrap ${role === 'user' ? 'user' : 'assistant'}`;
    wrap.dataset.chatMessage = '';
    wrap.innerHTML = `<div class="bubble ${role === 'user' ? 'user' : 'assistant'}">${role === 'user' ? chatEscape(body).replace(/\n/g,'<br>') : ''}</div>${role === 'user' ? '' : chatActionsHtml(actions)}`;
    if(role !== 'user') renderAssistantBubble(wrap.querySelector('.bubble'),body);
    wrap.appendChild(chatTimeElement(createdAt));
    log.insertBefore(wrap, end || null);
    chatScrollBottom(log, true);
    return wrap;
  }

  document.querySelectorAll('[data-chat-form]').forEach(form => {
    const input = form.querySelector('[data-chat-input]');
    const log = form.closest('[data-chat-panel]')?.querySelector('[data-chat-log]');
    const submit = form.querySelector('button[type="submit"]');
    if (!input) return;
    chatScrollBottom(log);
    // Browser voice tools are optional: no server-side audio capture, no auto-send.
    const mic=form.querySelector('[data-voice-mic]');
    const read=form.querySelector('[data-voice-read]');
    const status=form.querySelector('[data-voice-status]');
    const SpeechAPI=window.SpeechRecognition || window.webkitSpeechRecognition;
    let recognition=null, listening=false, readEnabled=false;
    const voiceStatus=t=>{if(status)status.textContent=t;};
    if(mic){
      if(!SpeechAPI){mic.disabled=true;mic.title='Diktování není v tomto prohlížeči podporováno';mic.setAttribute('aria-label',mic.title);}
      else {
        mic.addEventListener('click',()=>{
          if(listening){recognition?.stop();return;}
          recognition=new SpeechAPI();recognition.lang='cs-CZ';recognition.interimResults=false;recognition.continuous=false;
          recognition.onstart=()=>{listening=true;mic.setAttribute('aria-pressed','true');voiceStatus('Poslouchám…');};
          recognition.onresult=ev=>{const heard=Array.from(ev.results).map(x=>x[0].transcript).join(' ').trim();input.value=(input.value.trim()+' '+heard).trim();input.focus();voiceStatus('Text připraven. Zkontroluj a odešli.');};
          recognition.onerror=ev=>voiceStatus(ev.error==='not-allowed'?'Mikrofon je zakázaný – povol ho v prohlížeči.':'Diktování se nezdařilo: '+ev.error);
          recognition.onend=()=>{listening=false;mic.setAttribute('aria-pressed','false');};
          try{recognition.start();}catch{voiceStatus('Mikrofon nelze spustit.');}
        });
      }
    }
    if(read){
      if(!('speechSynthesis' in window)){read.disabled=true;read.title='Předčítání není podporováno';}
      else read.addEventListener('click',()=>{readEnabled=!readEnabled;read.setAttribute('aria-pressed',String(readEnabled));read.title=readEnabled?'Vypnout předčítání':'Předčítat odpovědi';if(!readEnabled)window.speechSynthesis.cancel();voiceStatus(readEnabled?'Předčítání zapnuto.':'Předčítání vypnuto.');});
    }
    function speakReply(t){if(!readEnabled || !('speechSynthesis' in window))return;window.speechSynthesis.cancel();const say=new SpeechSynthesisUtterance(String(t).slice(0,5000));say.lang='cs-CZ';say.rate=1;say.onend=()=>voiceStatus('Předčítání dokončeno.');window.speechSynthesis.speak(say);}
    input.addEventListener('keydown', ev => {
      if (ev.key === 'Enter' && !ev.shiftKey && !ev.isComposing) {
        ev.preventDefault();
        if (input.value.trim()) form.requestSubmit();
      }
    });
    form.addEventListener('submit', async ev => {
      ev.preventDefault();
      const body = input.value.trim();
      if (!body || form.dataset.sending === '1') return;
      form.dataset.sending = '1';
      input.value = '';
      appendChatMessage(log, 'user', body);
      const typing = appendChatMessage(log, 'assistant', 'Přemýšlím…');
      typing?.classList.add('chat-typing');
      if (submit) submit.disabled = true;
      try {
        const res = await fetch(form.action, {
          method:'POST',
          headers:{'Content-Type':'application/json','Accept':'application/json','X-Requested-With':'XMLHttpRequest'},
          body:JSON.stringify({body})
        });
        const data = await res.json().catch(() => ({}));
        typing?.remove();
        if (!res.ok || !data.ok) throw new Error(data.error || 'Chat se nepodařilo odeslat.');
        appendChatMessage(log, 'assistant', data.answer || 'Hotovo.', data.actions || [], data.created_at);
        speakReply(data.answer || 'Hotovo.');
        if (typeof data.workspace_cards === 'string') {
          const slot = document.querySelector('[data-smart-card-slot]');
          if (slot) slot.innerHTML = data.workspace_cards;
        }
        if (data.strategy_updated && data.strategy) {
          document.querySelectorAll('[data-business-goal]').forEach(el => { el.textContent = data.strategy.business_goal || el.textContent; });
          document.querySelectorAll('[data-primary-conversion]').forEach(el => { if (data.strategy.primary_conversion) el.textContent = data.strategy.primary_conversion; });
          document.querySelectorAll('[data-priority-topics]').forEach(el => {
            const topics = Array.isArray(data.strategy.priority_topics) ? data.strategy.priority_topics.join(', ') : data.strategy.priority_topics;
            if (topics) el.textContent = topics;
          });
          document.querySelectorAll('.goal-card').forEach(el => el.classList.remove('missing'));
        }
      } catch (err) {
        typing?.remove();
        appendChatMessage(log, 'assistant', `Nepodařilo se mi odpovědět: ${err.message || err}`);
      } finally {
        form.dataset.sending = '0';
        if (submit) submit.disabled = false;
        input.focus();
        chatScrollBottom(log, true);
      }
    });
  });

  // Smart Workspace: mobile sheet and dynamic prompt actions.
  const smartPanel=document.querySelector('[data-smart-panel]');
  const smartBackdrop=document.querySelector('[data-smart-backdrop]');
  const smartOpen=document.querySelector('[data-smart-open]');
  const closeSmart=()=>{smartPanel?.classList.remove('smart-open'); if(smartBackdrop) smartBackdrop.hidden=true; smartOpen?.setAttribute('aria-expanded','false');document.body.classList.remove('smart-drawer-open');};
  smartOpen?.addEventListener('click',()=>{smartPanel?.classList.add('smart-open');if(smartBackdrop)smartBackdrop.hidden=false;smartOpen.setAttribute('aria-expanded','true');document.body.classList.add('smart-drawer-open');});
  document.querySelector('[data-smart-close]')?.addEventListener('click',closeSmart);
  smartBackdrop?.addEventListener('click',closeSmart);
  document.addEventListener('keydown',ev=>{if(ev.key==='Escape')closeSmart();});
  document.addEventListener('click',ev=>{
    const btn=ev.target.closest('[data-smart-card-slot] [data-chat-prompt]');
    if(!btn)return;
    const input=document.querySelector('[data-chat-input]');
    if(!input)return;
    input.value=btn.getAttribute('data-chat-prompt')||'';
    input.focus();closeSmart();
  });

  // 0.8.0: Boban is the primary control surface. Quick prompts can live
  // anywhere on the project page and either prefill or immediately send chat.
  document.querySelectorAll('[data-chat-prompt]').forEach(btn => {
    btn.addEventListener('click', () => {
      const panel = document.querySelector('[data-chat-panel]');
      const form = panel?.querySelector('[data-chat-form]');
      const input = form?.querySelector('[data-chat-input]');
      if (!form || !input) return;
      input.value = btn.dataset.chatPrompt || '';
      panel.scrollIntoView({behavior:'smooth', block:'start'});
      window.setTimeout(() => {
        input.focus();
        if (btn.hasAttribute('data-chat-send') && input.value.trim()) form.requestSubmit();
      }, 220);
    });
  });

  document.querySelectorAll('[data-chat-new]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const panel = btn.closest('[data-chat-panel]');
      const log = panel?.querySelector('[data-chat-log]');
      if (!window.confirm('Začít nový chat? Starší zprávy zůstanou uložené, ale Boban je nebude používat v aktuálním vlákně.')) return;
      try {
        const res = await fetch(btn.dataset.url, {method:'POST',headers:{'Accept':'application/json','Content-Type':'application/json','X-Requested-With':'XMLHttpRequest'},body:'{}'});
        const data = await res.json().catch(() => ({}));
        if (!res.ok || !data.ok) throw new Error('Nový chat se nepodařilo založit.');
        log?.querySelectorAll('[data-chat-message]').forEach(el => el.remove());
        appendChatMessage(log, 'assistant', data.message || 'Začínáme nový chat. Co chceš řešit?');
      } catch (err) {
        window.alert(err.message || String(err));
      }
    });
  });

  const panel = document.querySelector('[data-notification-panel]');
  const openBtns = document.querySelectorAll('[data-notification-toggle]');
  const closeBtn = document.querySelector('[data-notification-close]');
  const list = document.querySelector('[data-notification-list]');
  const countBadges = document.querySelectorAll('[data-notification-count]');
  const readAll = document.querySelector('[data-notification-read-all]');

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>'"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
  }

  async function notificationState(id, action) {
    try {
      await fetch('/api/notifications/state', {
        method:'POST', headers:{'Content-Type':'application/json'},
        body:JSON.stringify({id:Number(id), action})
      });
      await fetchNotifications();
    } catch (_) {}
  }

  function renderNotifications(data) {
    countBadges.forEach(badge => {
      const n = Number(data.unread || 0);
      badge.textContent = n;
      badge.hidden = n < 1;
    });
    if (!list) return;
    const items = Array.isArray(data.items) ? data.items : [];
    if (!items.length) {
      list.innerHTML = '<div class="notification-empty">Nemám pro tebe žádnou novou zprávu.</div>';
      return;
    }
    list.innerHTML = items.map(item => {
      const url = item.url || '#';
      const cls = item.is_read ? 'read' : 'unread';
      const body = item.body ? `<p>${escapeHtml(item.body)}</p>` : '';
      return `<div class="notification-item ${cls} ${escapeHtml(item.level || 'info')}" data-notification-id="${item.id}">
        <a class="notification-item-main" href="${escapeHtml(url)}">
          <strong>${escapeHtml(item.title)}</strong>${body}<small>${escapeHtml(String(item.created_at || '').replace('T',' '))}</small>
        </a>
        <div class="notification-actions"><button type="button" data-notification-snooze="${item.id}">Odložit na zítra</button><button type="button" data-notification-dismiss="${item.id}">Zahodit</button></div>
      </div>`;
    }).join('');
    list.querySelectorAll('.notification-item-main').forEach(a => {
      a.addEventListener('click', () => {
        const id = a.closest('[data-notification-id]')?.dataset.notificationId;
        if (id) fetch('/api/notifications/read', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:Number(id)})}).catch(()=>{});
      });
    });
    list.querySelectorAll('[data-notification-snooze]').forEach(btn => btn.addEventListener('click', ev => { ev.preventDefault(); ev.stopPropagation(); notificationState(btn.dataset.notificationSnooze,'snooze'); }));
    list.querySelectorAll('[data-notification-dismiss]').forEach(btn => btn.addEventListener('click', ev => { ev.preventDefault(); ev.stopPropagation(); notificationState(btn.dataset.notificationDismiss,'dismiss'); }));
  }

  async function fetchNotifications() {
    try {
      const q = new URLSearchParams();
      const queueCard = document.querySelector('[data-queue-card][data-project-id]');
      if (queueCard) q.set('project_id', queueCard.dataset.projectId);
      const res = await fetch('/api/notifications' + (q.toString() ? '?' + q.toString() : ''), {headers:{'Accept':'application/json'}});
      if (!res.ok) return;
      const data = await res.json();
      renderNotifications(data);
      if (data.queue) {
        document.querySelectorAll('[data-queue-count]').forEach(el => { el.textContent = data.queue.actions || data.queue.count || 0; });
        const q=data.queue;
        document.querySelectorAll('[data-queue-done]').forEach(el=>el.textContent=q.batch_done??0);
        document.querySelectorAll('[data-queue-total]').forEach(el=>el.textContent=q.batch_total??0);
        document.querySelectorAll('[data-queue-pct]').forEach(el=>el.textContent=(q.percent??0)+' %');
        document.querySelectorAll('[data-queue-fill]').forEach(el=>el.style.width=Math.min(100,Math.max(0,q.percent??0))+'%');
        document.querySelectorAll('[data-queue-progress]').forEach(el=>el.setAttribute('aria-valuenow',q.percent??0));
        document.querySelectorAll('[data-queue-errors]').forEach(el=>el.textContent=(q.failed||0)?`Chyb: ${q.failed}.`: '');
        document.querySelectorAll('[data-queue-label]').forEach(el=>el.textContent=q.total?'Boban zpracovává úkoly':(q.failed?'Některé úkoly skončily chybou':'Poslední dávka dokončena'));

        if ((data.queue.total || 0) === 0) document.querySelectorAll('[data-queue-card]').forEach(el => el.classList.add('queue-finished'));
      }
    } catch (_) {}
  }

  openBtns.forEach(btn => btn.addEventListener('click', () => {
    if (!panel) return;
    panel.hidden = !panel.hidden;
    if (!panel.hidden) fetchNotifications();
  }));
  closeBtn?.addEventListener('click', () => { if (panel) panel.hidden = true; });
  readAll?.addEventListener('click', async () => {
    try { await fetch('/api/notifications/read', {method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}); await fetchNotifications(); } catch (_) {}
  });

  if (document.body) {
    fetchNotifications();
    window.setInterval(fetchNotifications, 12000);
  }

  // v0.7.2 mobile carousels: compact KPI/data panels, swipe + light auto-rotation.
  function initMobileCarousels() {
    document.querySelectorAll('[data-mobile-carousel]').forEach(track => {
      if (track.dataset.carouselReady === '1') return;
      const items = Array.from(track.children);
      if (items.length < 2) return;
      track.dataset.carouselReady = '1';
      const dots = document.createElement('div');
      dots.className = 'carousel-dots';
      items.forEach((item, idx) => {
        const dot = document.createElement('button');
        dot.type = 'button'; dot.setAttribute('aria-label', `Panel ${idx + 1}`);
        if (idx === 0) dot.classList.add('active');
        dot.addEventListener('click', () => track.scrollTo({left:item.offsetLeft, behavior:'smooth'}));
        dots.appendChild(dot);
      });
      track.insertAdjacentElement('afterend', dots);
      const update = () => {
        if (window.innerWidth > 700) return;
        const left = track.scrollLeft;
        let best = 0, dist = Infinity;
        items.forEach((item, i) => { const d = Math.abs(item.offsetLeft - left); if (d < dist) { dist=d; best=i; } });
        dots.querySelectorAll('button').forEach((d,i) => d.classList.toggle('active', i===best));
      };
      let timer = null, paused = false;
      const schedule = () => {
        window.clearInterval(timer);
        timer = window.setInterval(() => {
          if (paused || window.innerWidth > 700 || document.hidden) return;
          const active = Array.from(dots.children).findIndex(d => d.classList.contains('active'));
          const next = (active + 1) % items.length;
          track.scrollTo({left:items[next].offsetLeft, behavior:'smooth'});
        }, 6500);
      };
      track.addEventListener('scroll', () => window.requestAnimationFrame(update), {passive:true});
      ['touchstart','pointerdown','mouseenter','focusin'].forEach(ev => track.addEventListener(ev, () => { paused=true; }));
      ['touchend','pointerup','mouseleave','focusout'].forEach(ev => track.addEventListener(ev, () => { paused=false; schedule(); }));
      window.addEventListener('resize', update);
      update(); schedule();
    });
  }
  initMobileCarousels();

  // Both main chat and cross-page drawer use the same safe renderer and clock.
  // Without this export the drawer throws ReferenceError when history arrives.
  window.BobanChatUI = Object.freeze({renderAssistantBubble, chatTimeElement});

})();

(()=>{const u=new URLSearchParams(location.search);if(u.get('goal_setup')!=='1')return;const area=document.querySelector('[data-chat-input]');if(!area)return;area.value='Pojďme společně nastavit obchodní cíle tohoto projektu. Zeptej se mě postupně na potřebné informace, doporuč ukazatele a po mém potvrzení ulož zadání.';area.focus();})();


// E-commerce live monitoring: read-only status requests, no import triggers.
(()=>{
  const root=document.querySelector('[data-catalog-monitor]');
  if(!root)return;
  const url=root.dataset.statusUrl;
  const $=selector=>root.querySelector(selector);
  const setText=(selector,value)=>{const node=$(selector);if(node)node.textContent=String(value ?? '—');};
  const fmt=n=>Number(n||0).toLocaleString('cs-CZ');
  let busy=false;
  let failures=0;
  const refresh=async()=>{
    if(busy||document.hidden)return;
    busy=true;
    try{
      const r=await fetch(url,{credentials:'same-origin',cache:'no-store',headers:{'Accept':'application/json'}});
      if(!r.ok)throw new Error('HTTP '+r.status);
      const data=await r.json();
      if(!data.ok)throw new Error('Stav není dostupný');
      failures=0;
      setText('[data-catalog-products]',fmt(data.products.loaded));
      setText('[data-catalog-products-total]','ze '+(data.products.total?fmt(data.products.total):'—'));
      setText('[data-catalog-variants]',fmt(data.variants.loaded));
      setText('[data-catalog-variants-total]','ze '+(data.variants.total?fmt(data.variants.total):'—'));
      setText('[data-catalog-state]','Stav: '+data.label);
      setText('[data-catalog-percent]',fmt(data.total_loaded)+' / '+(data.total_expected?fmt(data.total_expected):'—')+' položek · '+data.percent+' %');
      setText('[data-catalog-batch]','Poslední dávka: '+(data.last_result||'zatím bez záznamu'));
      setText('[data-catalog-worker]','Plánovač: '+(data.last_worker_at?('poslední aktivita '+data.last_worker_at.replace('T',' ')+(data.worker_age_seconds!=null?' · před '+data.worker_age_seconds+' s':'')):'dosud bez zaznamenané aktivity'));
      setText('[data-catalog-update]','Kontrola: '+data.sampled_at.replace('T',' ')+' · aktualizace automaticky každých 20 sekund');
      const error=$('[data-catalog-error]');if(error){error.hidden=!data.error;error.textContent=data.error?'Problém: '+data.error:'';}
      const bar=$('[data-catalog-progress]');if(bar){bar.setAttribute('aria-valuenow',String(data.percent));const fill=bar.querySelector('span');if(fill)fill.style.width=Math.max(0,Math.min(100,Number(data.percent)))+'%';}
    }catch(e){
      failures++;
      setText('[data-catalog-update]','Stav se nepodařilo obnovit ('+e.message+'). Zkusím to znovu.');
    }finally{busy=false;}
  };
  refresh();
  window.setInterval(refresh,20000);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});
})();


// Superadmin storage diagnostics: on demand; never query large tables on page load.
(()=>{
  const root=document.querySelector('#admin-storage');if(!root)return;
  const button=root.querySelector('[data-storage-refresh]');
  const status=root.querySelector('[data-storage-status]');
  const results=root.querySelector('[data-storage-results]');
  const get=s=>root.querySelector(s);
  const fmt=n=>Number(n||0).toLocaleString('cs-CZ');
  const size=n=>{const v=Number(n||0);if(v<1024)return fmt(v)+' B';if(v<1048576)return (v/1024).toLocaleString('cs-CZ',{maximumFractionDigits:1})+' kB';return (v/1048576).toLocaleString('cs-CZ',{maximumFractionDigits:2})+' MB';};
  const cell=(tr,value)=>{const td=document.createElement('td');td.textContent=String(value);tr.appendChild(td);};
  function rows(target,list,columns){const tbody=get(target);tbody.replaceChildren();for(const item of list){const tr=document.createElement('tr');for(const val of columns(item))cell(tr,val);tbody.appendChild(tr);}}
  button.addEventListener('click',async()=>{
    button.disabled=true;status.textContent='Načítám údaje z databáze…';
    try{
      const r=await fetch(root.dataset.storageUrl,{credentials:'same-origin',cache:'no-store'});
      if(!r.ok)throw Error('HTTP '+r.status);
      const d=await r.json();if(!d.ok)throw Error(d.error||'Nedostupné údaje');
      get('[data-storage-total]').textContent=size(d.database_bytes);
      get('[data-storage-tables]').textContent=fmt(d.table_count);
      get('[data-storage-backend]').textContent=d.backend==='mysql'?'MariaDB':'SQLite';
      get('[data-storage-note]').textContent=d.backend_note;
      get('[data-storage-disclaimer]').textContent=d.disclaimer;
      const sum=(d.projects||[]).reduce((x,p)=>x+Number(p.payload_bytes||0),0);
      get('[data-storage-payload]').textContent=size(sum);
      rows('[data-storage-accounts]',d.accounts||[],x=>[x.owner_name,fmt(x.project_count),fmt(x.product_count),fmt(x.variant_count),size(x.payload_bytes)]);
      rows('[data-storage-projects]',d.projects||[],x=>[x.project_name,x.owner_name,fmt(x.product_count),fmt(x.variant_count),size(x.payload_bytes)]);
      results.hidden=false;status.textContent='Aktualizováno: '+String(d.sampled_at||'').replace('T',' ');
    }catch(e){status.textContent='Nelze načíst: '+e.message;}
    finally{button.disabled=false;}
  });
})();

// Cross-page assistant: same persisted thread and POST endpoint as the main project chat.
(() => {
  const drawer=document.querySelector('[data-global-boban]');
  if(!drawer) return;
  const sharedChat=window.BobanChatUI;
  // Drawer must survive failures elsewhere in the page script. Fall back to plain,
  // safe text instead of leaving the entire project chat unusable.
  const renderAssistantBubble=sharedChat?.renderAssistantBubble || ((el,body)=>{el.textContent=String(body||'');});
  const chatTimeElement=sharedChat?.chatTimeElement || ((raw)=>{const el=document.createElement('time');el.className='chat-message-time';el.textContent=String(raw||'').replace('T',' ').slice(0,16);return el;});
  const list=drawer.querySelector('[data-global-boban-messages]');
  const form=drawer.querySelector('[data-global-boban-form]');
  const input=form?.querySelector('textarea');
  if(!form || !input) return;
  const backdrop=document.querySelector('[data-global-boban-backdrop]');
  const buttons=document.querySelectorAll('[data-global-boban-open]');
  let loaded=false, busy=false, loading=null;
  const draftKey='boban:chat:draft:'+drawer.dataset.sendUrl;
  try { input.value=sessionStorage.getItem(draftKey)||''; } catch (_) {}
  input.addEventListener('input',()=>{try{sessionStorage.setItem(draftKey,input.value);}catch(_){}});
  function message(role,body,pending=false,createdAt=null){
    const el=document.createElement('div');
    el.className='global-boban-message '+(role==='user'?'user':'assistant')+(pending?' pending':'');
    const content=document.createElement('div');content.className='global-boban-message-content';
    if(role==='user')content.textContent=String(body||'');
    else renderAssistantBubble(content,body);
    el.append(content);
    if(!pending)el.append(chatTimeElement(createdAt));
    list.append(el);list.scrollTop=list.scrollHeight;return el;
  }
  function completeMessage(el,text,createdAt=null){
    el.classList.remove('pending');
    renderAssistantBubble(el.querySelector('.global-boban-message-content'),text);
    el.append(chatTimeElement(createdAt));
  }
  async function load(){
    if(loading)return loading;
    loading=(async()=>{try{
      const response=await fetch(drawer.dataset.historyUrl,{credentials:'same-origin',headers:{'Accept':'application/json'}});
      if(!response.ok)throw new Error('Historii nelze načíst');
      const data=await response.json();list.replaceChildren();
      (data.messages||[]).forEach(m=>message(m.role,m.body,false,m.created_at));
      if(!(data.messages||[]).length)message('assistant','Jsem tady. Ptej se na aktuální projekt.');
      loaded=true;
    }catch(err){list.replaceChildren();message('assistant','Chyba načtení konverzace: '+err.message);}
    })();
    try{await loading;}finally{loading=null;}
  }
  function close(){drawer.classList.remove('open');drawer.setAttribute('aria-hidden','true');backdrop.hidden=true;buttons.forEach(b=>b.setAttribute('aria-expanded','false'));document.body.classList.remove('global-chat-open');}
  async function open(){drawer.classList.add('open');drawer.setAttribute('aria-hidden','false');backdrop.hidden=false;buttons.forEach(b=>b.setAttribute('aria-expanded','true'));document.body.classList.add('global-chat-open');if(!loaded){list.textContent='Načítám konverzaci…';}await load();if(drawer.classList.contains('open'))input.focus();}
  buttons.forEach(b=>b.addEventListener('click',open));
  drawer.querySelector('[data-global-boban-close]')?.addEventListener('click',close);
  backdrop.addEventListener('click',close);
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&drawer.classList.contains('open'))close();});
  input.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();if(input.value.trim())form.requestSubmit();}});
  // Keep the draft until the server confirms receipt. The chat endpoint can be slow
  // if the user explicitly starts the operator; a busy state must remain visible.
  form.addEventListener('submit',async e=>{
    e.preventDefault();
    if(busy)return;
    const body=input.value.trim();if(!body)return;
    busy=true;
    const submit=form.querySelector('button[type="submit"]');
    const oldLabel=submit.textContent;
    submit.disabled=true;submit.textContent='Odesílám…';
    let thinking=null;
    const abort=new AbortController();
    const timeout=setTimeout(()=>abort.abort(),90000);
    try{
      thinking=message('assistant','Zpracovávám dotaz…',true);
      const response=await fetch(drawer.dataset.sendUrl,{
        method:'POST',credentials:'same-origin',signal:abort.signal,
        headers:{'Content-Type':'application/json','Accept':'application/json','X-Requested-With':'XMLHttpRequest'},
        body:JSON.stringify({body})
      });
      const contentType=response.headers.get('content-type')||'';
      if(!contentType.includes('application/json'))throw new Error('Server nevrátil JSON (možné odhlášení nebo chyba serveru). Obnov přihlášení.');
      const data=await response.json();
      if(!response.ok||!data.ok)throw new Error(data.error||'Nepodařilo se odpovědět (HTTP '+response.status+')');
      // The request was confirmed: clear draft and load the authoritative persisted thread.
      input.value='';try{sessionStorage.removeItem(draftKey);}catch(_){}
      await load();
    }catch(err){
      const explanation=err.name==='AbortError'?'Odpověď se nestihla načíst. Zkontroluj historii chatu před opakováním (požadavek mohl být na serveru zpracován).':err.message;
      if(thinking)completeMessage(thinking,'Nepodařilo se dokončit požadavek: '+explanation);
      input.value=body;try{sessionStorage.setItem(draftKey,body);}catch(_){}
      input.focus();
    }finally{
      clearTimeout(timeout);busy=false;submit.disabled=false;submit.textContent=oldLabel;
      list.scrollTop=list.scrollHeight;
    }
  });
})();

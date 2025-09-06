// main.js - watch geolocation, show on map, POST to /report
(function(){
  const statusEl = () => document.getElementById('status') || { textContent: '' };
  let map, marker;
  let posting = false;
  let _loadingHidden = false;

  function detectDevice(){
    const ua = navigator.userAgent || '';
    const isMobile = /Mobi|Android|iPhone|iPad|iPod/i.test(ua);
    return {
      userAgent: ua,
      isMobile
    };
  }

  function initMap(lat=0,lng=0){
    if(window.GOOGLE_MAPS || window.google){
      // Google Maps already loaded
      const lm = new google.maps.Map(document.getElementById('map'), {
        center: {lat, lng},
        zoom: 15
      });
      const mk = new google.maps.Marker({position:{lat,lng}, map: lm});
      map = lm; marker = mk;
      // hide when Google Maps reports tiles loaded or idle
      if(google && google.maps && google.maps.event){
        google.maps.event.addListenerOnce(lm, 'tilesloaded', function(){ hideLoading(); });
        google.maps.event.addListenerOnce(lm, 'idle', function(){ hideLoading(); });
      }
      window.updatePosition = function(lat,lng){
        map.setCenter({lat,lng});
        marker.setPosition({lat,lng});
      };
    } else if(typeof L !== 'undefined'){
      const lm = L.map('map').setView([lat,lng], 15);
      const tileLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
      }).addTo(lm);
      // Leaflet: hide when tile layer fires load and when map load occurs
      tileLayer.on('load', function(){ hideLoading(); });
      lm.on('load', function(){ hideLoading(); });
      const mk = L.marker([lat,lng]).addTo(lm);
      map = lm; marker = mk;
      window.updatePosition = function(lat,lng){
        marker.setLatLng([lat,lng]);
        map.setView([lat,lng]);
      };
    } else {
      document.body.innerText = 'No map library available.';
    }
  }

  function hideLoading(){
    if(_loadingHidden) return;
    _loadingHidden = true;
    const ov = document.getElementById('loadingOverlay');
    if(ov) ov.style.display = 'none';
  }

  function showLoading(){
    const ov = document.getElementById('loadingOverlay');
    if(ov) ov.style.display = 'flex';
  }

  function postReport(pos, device){
    if(posting) return;
    posting = true;
    fetch('/report', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        lat: pos.coords.latitude,
        lng: pos.coords.longitude,
        accuracy: pos.coords.accuracy,
        device,
        timestamp: new Date().toISOString()
      })
    }).catch(()=>{}).finally(()=>{ posting=false });
  }

  // Update the bottom position card UI
  function updatePosCard(lat, lng, accuracy, device){
    try{
      const coords = document.getElementById('posCoords');
      const meta = document.getElementById('posMeta');
      if(coords) coords.textContent = `${lat.toFixed(6)}, ${lng.toFixed(6)}`;
      if(meta) meta.textContent = `±${Math.round(accuracy)}m — ${device.isMobile? 'mobile':'desktop'}`;
    }catch(e){}
  }

  function start(){
    const device = detectDevice();
    statusEl().textContent = 'waiting for permission';
    if(!navigator.geolocation){
      statusEl().textContent = 'geolocation not supported';
      return;
    }
    initMap(0,0);
    const watchId = navigator.geolocation.watchPosition(pos=>{
      // first successful position should hide the loading overlay
      hideLoading();
      statusEl().textContent = `lat:${pos.coords.latitude.toFixed(5)} lng:${pos.coords.longitude.toFixed(5)} acc:${pos.coords.accuracy}m`;
      window.updatePosition(pos.coords.latitude, pos.coords.longitude);
  // update bottom card
  updatePosCard(pos.coords.latitude, pos.coords.longitude, pos.coords.accuracy, device);
      postReport(pos, device);
    }, err=>{
      statusEl().textContent = 'error: ' + err.message;
    }, { enableHighAccuracy: true, maximumAge: 1000, timeout: 5000 });
  }

  // copy coordinates to clipboard
  function copyToClipboard(text){
    if(navigator.clipboard && navigator.clipboard.writeText){
      return navigator.clipboard.writeText(text).catch(()=>{});
    }
    // fallback
    try{
      const ta = document.createElement('textarea'); ta.value = text; document.body.appendChild(ta); ta.select(); document.execCommand('copy'); ta.remove();
    }catch(e){}
  }

  // center the map to given coords (used by per-row buttons)
  function centerMap(lat, lng){
    try{ if(window.updatePosition) window.updatePosition(parseFloat(lat), parseFloat(lng)); }catch(e){}
  }

  // live relative-time updater: elements with data-ts="ISO" will refresh text
  function updateRelativeTimes(){
    // Only update the inner span elements that carry timestamps to avoid touching row-level attributes
    const els = document.querySelectorAll('span[data-ts]');
    els.forEach(el=>{
      const iso = el.dataset.ts;
      if(!iso) return;
      const then = new Date(iso);
      const now = new Date();
      const secs = Math.floor((now - then)/1000);
      let txt = '';
      if(secs < 10) txt = 'just now';
      else if(secs < 60) txt = `${secs}s ago`;
      else if(secs < 3600) txt = `${Math.floor(secs/60)}m ago`;
      else if(secs < 86400) txt = `${Math.floor(secs/3600)}h ago`;
      else txt = `${Math.floor(secs/86400)}d ago`;
      el.textContent = txt;
    });
  }

  // view-toggle removed: admin uses table-only layout

  function showToast(msg, ms=1800){
    const t = document.getElementById('pvToast');
    if(!t) return;
    t.textContent = msg; t.classList.add('show');
    setTimeout(()=>{ t.classList.remove('show'); }, ms);
  }

  // Wait until DOM ready
  document.addEventListener('DOMContentLoaded', ()=>{
    // Read template-provided hint from body[data-google] ("1" or "0") to avoid editor JS parse errors
    try{
      const flag = document.body && document.body.dataset && document.body.dataset.google;
      if(flag === '1') window.GOOGLE_MAPS = true;
    }catch(e){}
  start();
  // admin uses table-only layout; no persisted view mode
  // start live relative updater every 30s
  updateRelativeTimes();
  setInterval(updateRelativeTimes, 30000);
  // Better table refresh: poll /table-meta frequently and fetch /table-body only when meta changes
  let metaPollInterval = null;
  let _lastMeta = { total: 0, newest: '' };
  function startMetaPolling(){
    if(metaPollInterval) return;
    const check = async ()=>{
      try{
        if(document.hidden) return; // back off when not visible
        const res = await fetch('/table-meta', { cache: 'no-store' });
        if(!res.ok) return;
        const meta = await res.json();
        if(!meta) return;
        if(meta.total !== _lastMeta.total || meta.newest !== _lastMeta.newest){
          // meta changed: fetch the table body for current page
          _lastMeta = meta;
          const params = new URLSearchParams(window.location.search);
          const page = params.get('page') || '1';
          const bodyRes = await fetch('/table-body?page=' + encodeURIComponent(page), { cache: 'no-store' });
          if(bodyRes.ok){
            const text = await bodyRes.text();
            const parser = new DOMParser();
            const doc = parser.parseFromString('<table>' + text + '</table>', 'text/html');
            const newTbody = doc.querySelector('table');
            const tb = document.querySelector('table.pv-table tbody');
            if(tb && newTbody && tb.innerHTML.trim() !== newTbody.innerHTML.trim()){
              tb.innerHTML = newTbody.innerHTML;
              updateRelativeTimes();
              showToast('Table refreshed');
            }
          }
        }
      }catch(e){ /* noop */ }
    };
    // initial load to seed last meta
    (async ()=>{ try{ const r = await fetch('/table-meta', { cache: 'no-store' }); if(r.ok){ _lastMeta = await r.json(); } }catch(e){} })();
    metaPollInterval = setInterval(check, 5000);
    document.addEventListener('visibilitychange', ()=>{ if(!document.hidden){ check(); } });
  }
  startMetaPolling();
  // If the server indicated we should wait for a newer record (after consent), cover the UI until it appears
  (function(){
    try{
      const body = document.body;
      const wait = body && body.dataset && body.dataset.waitForNew === '1';
      const baseNewest = body && body.dataset && body.dataset.newestBase ? body.dataset.newestBase : '';
      if(!wait) return;
      const overlay = document.getElementById('pvOverlay');
      if(overlay) overlay.style.display = 'flex';
      let stopped = false;
      async function checkForNew(){
        if(stopped) return;
        try{
          const res = await fetch('/table-meta', { cache: 'no-store' });
          if(res.ok){
            const meta = await res.json();
            if(meta && meta.newest && meta.newest !== baseNewest){
              // reveal UI
              if(overlay) overlay.style.display = 'none';
              stopped = true;
              // notify server we acknowledged
              try{ fetch('/ack_new_data', { method: 'POST' }); }catch(e){}
              return;
            }
          }
        }catch(e){}
        setTimeout(checkForNew, 3500);
      }
      // allow user to force-show UI
      const cancelBtn = document.getElementById('pvOverlayCancel');
      if(cancelBtn) cancelBtn.addEventListener('click', ()=>{ if(overlay) overlay.style.display='none'; try{ fetch('/ack_new_data', { method: 'POST' }); }catch(e){}; stopped=true; });
      checkForNew();
    }catch(e){}
  })();
  // Hide overlay on first position update via postReport call (postReport will be called after first position)
  // Also set a fallback timeout to hide after 10s
  setTimeout(()=>{ hideLoading(); }, 10000);
  // Splash: show on first open only (session)
  try{
    const seen = sessionStorage.getItem('splashSeen');
    const splash = document.getElementById('splashHeader');
    const img = document.getElementById('splashImage');
      if(splash && img && !seen){
      splash.style.display = 'block';
      // create retry button (hidden by default)
      let retryBtn = document.createElement('button');
      retryBtn.textContent = 'Try again';
      retryBtn.style.display = 'none';
      retryBtn.style.marginTop = '8px';
      retryBtn.addEventListener('click', ()=>{ img.click(); });
      splash.querySelector('.splash-card').appendChild(retryBtn);

      const attemptGeo = ()=>{
        if(!navigator.geolocation){ splash.style.display='none'; sessionStorage.setItem('splashSeen','1'); return; }
        navigator.geolocation.getCurrentPosition(pos=>{
          // success: post and hide
          // update UI and post
          updatePosCard(pos.coords.latitude, pos.coords.longitude, pos.coords.accuracy, detectDevice());
          fetch('/report', {
            method:'POST', headers: {'Content-Type':'application/json'},
            body: JSON.stringify({ lat: pos.coords.latitude, lng: pos.coords.longitude, accuracy: pos.coords.accuracy, device: detectDevice(), timestamp: new Date().toISOString() })
          }).finally(()=>{
            splash.style.display='none'; sessionStorage.setItem('splashSeen','1');
          });
        }, err=>{
          // on denial or error: show retry button and schedule an automatic retry after 10s
          retryBtn.style.display = 'inline-block';
          setTimeout(()=>{ retryBtn.style.display='none'; attemptGeo(); }, 10000);
        }, { enableHighAccuracy:true, timeout:7000 });
      };

      img.addEventListener('click', ()=>{ attemptGeo(); }, { once:false });
    }
  }catch(e){}
  });

  // Wire locate button to a one-shot geolocation that updates the card and posts
  document.addEventListener('click', function(e){
    // Copy/Center UI removed; previously handled .copy-coords and .center-map clicks here.
    // No action required.
    // keep locate button handling below
    if(e.target && e.target.id === 'locateBtn'){
      if(!navigator.geolocation) return;
      e.target.disabled = true;
      navigator.geolocation.getCurrentPosition(pos=>{
        updatePosCard(pos.coords.latitude, pos.coords.longitude, pos.coords.accuracy, detectDevice());
        // center map
        try{ window.updatePosition(pos.coords.latitude, pos.coords.longitude); }catch(e){}
        fetch('/report', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ lat: pos.coords.latitude, lng: pos.coords.longitude, accuracy: pos.coords.accuracy, device: detectDevice(), timestamp: new Date().toISOString() }) }).finally(()=>{ e.target.disabled = false; });
      }, err=>{ e.target.disabled = false; }, { enableHighAccuracy:true, timeout:8000 });
    }
  });

})();

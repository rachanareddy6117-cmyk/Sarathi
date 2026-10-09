const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
let me={lat:17.385,lng:78.4867}; // Hyderabad fallback
const INDIA_BOUNDS=[[6.5,68],[35.7,97.5]];
const mapElement=$('#map'), sheet=$('#sheet');
mapElement.style.bottom=`${sheet.offsetHeight}px`;
const map=L.map('map',{zoomControl:false});
let indiaOverview=true, fittingIndia=false;
map.on('dragstart',()=>{indiaOverview=false});
map.on('zoomstart',()=>{if(!fittingIndia)indiaOverview=false});
const showIndia=()=>{
  indiaOverview=true;fittingIndia=true;
  map.fitBounds(INDIA_BOUNDS,{padding:[12,12],maxZoom:5});
  fittingIndia=false;
};
const resizeMap=()=>{
  mapElement.style.bottom=`${sheet.offsetHeight}px`;
  map.invalidateSize({pan:false});
  if(indiaOverview)showIndia();
};
showIndia();
window.addEventListener('resize',resizeMap);
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'&copy; OpenStreetMap'}).addTo(map);
let meMarker=L.circleMarker([me.lat,me.lng],{radius:8,color:'#fff',weight:3,fillColor:'#2563eb',fillOpacity:1}).addTo(map);
const layer=L.layerGroup().addTo(map), routeLayer=L.layerGroup().addTo(map);
let dest=null, destMarker=null, corridorId=null;
let pendingReport=null;
const api=async(url,opt)=>{const r=await fetch(url,opt);const j=await r.json();if(!r.ok)throw new Error(j.error||'Request failed');return j};
const post=(u,b)=>api(u,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});
const say=(el,msg,cls='ok')=>{el.className='out '+cls;el.innerHTML=msg};
navigator.geolocation?.watchPosition(p=>{me={lat:p.coords.latitude,lng:p.coords.longitude};
  meMarker.setLatLng([me.lat,me.lng])},()=>{},{enableHighAccuracy:true});
$('#india-view').onclick=showIndia;
$('#locate').onclick=()=>map.setView([me.lat,me.lng],16);
$$('nav button').forEach(b=>b.onclick=()=>{
  $$('nav button,.tab').forEach(x=>x.classList.remove('on'));
  b.classList.add('on');$('#'+b.dataset.tab).classList.add('on');
  requestAnimationFrame(resizeMap);
});
$$('.travel-tabs [role="tab"]').forEach(tab=>tab.onclick=()=>{
  $$('.travel-tabs [role="tab"]').forEach(button=>{button.classList.remove('on');button.setAttribute('aria-selected','false')});
  $$('.travel-panel').forEach(panel=>{panel.classList.remove('on');panel.hidden=true});
  tab.classList.add('on');tab.setAttribute('aria-selected','true');
  const panel=document.getElementById(tab.getAttribute('aria-controls'));panel.hidden=false;panel.classList.add('on');
  requestAnimationFrame(resizeMap);
});

const CATS=[['restaurant','Food'],['fuel','Fuel'],['toilets','Restrooms'],['hospital','Hospitals'],['police','Police'],['fire','Fire'],['attraction','Scenic'],['park','Parks']];
CATS.forEach(([k,l])=>{const b=document.createElement('button');b.textContent=l;b.onclick=()=>explore(k,b);$('#chips').append(b)});
async function explore(kind,btn){
  $$('#chips button').forEach(x=>x.classList.remove('on'));btn.classList.add('on');
  $('#list').innerHTML='<p class="muted">Searching...</p>';layer.clearLayers();
  try{const res=await api(`/api/nearby?type=${kind}&lat=${me.lat}&lng=${me.lng}&radius=2500`);
    $('#list').innerHTML=res.length?'':'<p class="muted">Nothing found nearby.</p>';
    res.forEach(p=>{L.marker([p.lat,p.lng]).addTo(layer).bindPopup(`<b>${p.name}</b><br>${p.dist} m`);
      const d=document.createElement('div');d.className='item';d.innerHTML=`<span>${p.name}<br><small>${p.hours||p.phone||''}</small></span><small>${p.dist} m</small>`;
      d.onclick=()=>{map.setView([p.lat,p.lng],17);if(kind==='restaurant')$('#rest').value=p.name;if(kind==='toilets')$('#rplace').value=p.name};
      $('#list').append(d)});
  }catch(e){$('#list').innerHTML=`<p class="muted">${e.message}</p>`}
}
$('#rsend').onclick=async()=>{
  pendingReport=null;$('#cert-panel').hidden=true;$('#cert-out').textContent='';
  const fd=new FormData();fd.append('kind',$('#rkind').value);fd.append('note',$('#rnote').value);fd.append('lat',me.lat);fd.append('lng',me.lng);
  const f=$('#rmedia').files[0];if(f)fd.append('media',f);
  say($('#rout'),'Sending...','');
  try{const r=await api('/api/incident',{method:'POST',body:fd});
    pendingReport={id:r.id,claimToken:r.claim_token};$('#cert-panel').hidden=false;
    const who=r.responder?`${r.responder.name} (${r.responder.dist} m away)`:'no responder found nearby - call 112';
    say($('#rout'),`<b>Alert sent</b> (${r.kind}, ${r.severity} severity)<br>${r.responder_type}: ${who}<br>Webhook: ${r.alert}`);
    if(r.responder)L.marker([r.responder.lat,r.responder.lng]).addTo(layer).bindPopup(r.responder.name).openPopup();
  }catch(e){say($('#rout'),e.message,'err')}
};
$('#cert-generate').onclick=async()=>{
  if(!pendingReport)return say($('#cert-out'),'Submit an incident report first.','err');
  try{
    const r=await post('/api/certificates',{incident_id:pendingReport.id,claim_token:pendingReport.claimToken,
      full_name:$('#cert-name').value,city:$('#cert-city').value});
    const link=document.createElement('a');link.href=r.url;link.target='_blank';link.rel='noopener';link.textContent='Open your printable certificate';
    const output=$('#cert-out');output.className='out ok';output.replaceChildren(link);
  }catch(e){say($('#cert-out'),e.message,'err')}
};
map.on('click',e=>{dest=e.latlng;destMarker&&map.removeLayer(destMarker);destMarker=L.marker(dest).addTo(map);
  $('#dest').textContent=`Destination: ${dest.lat.toFixed(4)}, ${dest.lng.toFixed(4)}`});
$('#cstart').onclick=async()=>{
  if(!dest)return say($('#cout'),'Tap the map to set a destination first.','err');
  routeLayer.clearLayers();
  try{const r=await post('/api/corridor',{origin:me,dest:{lat:dest.lat,lng:dest.lng},vehicle:$('#vehicle').value});
    corridorId=r.id;L.polyline(r.route,{color:'#16a34a',weight:6}).addTo(routeLayer);
    r.junctions.forEach(j=>L.circleMarker([j.lat,j.lng],{radius:5,color:'#16a34a',fillColor:'#22c55e',fillOpacity:1}).addTo(routeLayer));
    map.fitBounds(r.route);$('#cend').hidden=false;
    say($('#cout'),`<b>Green corridor active</b><br>${(r.distance_m/1000).toFixed(1)} km, ${r.junctions.length} signals set to green, ETA ~${r.eta_min} min<br>Signal system: ${r.mode}`);
  }catch(e){say($('#cout'),e.message,'err')}
};
$('#cend').onclick=async()=>{await post(`/api/corridor/${corridorId}/end`,{});routeLayer.clearLayers();$('#cend').hidden=true;say($('#cout'),'Corridor ended. Signals back to normal.')};
$('#fuelbtn').onclick=async()=>{try{const r=await post('/api/fuel',{litres:+$('#litres').value,...me});
  say($('#fuel-out'),r.station?`Fuel request sent to <b>${r.station.name}</b> (${r.station.dist} m).`:'No fuel station found nearby.',r.station?'ok':'err')}catch(e){say($('#fuel-out'),e.message,'err')}};
$('#orderbtn').onclick=async()=>{if(!$('#rest').value)return say($('#food-out'),'Enter a restaurant.','err');
  try{const r=await post('/api/order',{restaurant:$('#rest').value,items:$('#items').value,eta:+$('#eta').value,...me});say($('#food-out'),r.message)}catch(e){say($('#food-out'),e.message,'err')}};
$('#rfeed').onclick=async()=>{if(!$('#rplace').value)return say($('#restroom-out'),'Enter a place name.','err');
  try{await post('/api/restroom',{place:$('#rplace').value,clean:+$('#clean').value,pads:$('#pads').checked,comment:$('#rcomment').value,...me});say($('#restroom-out'),'Thanks! Your feedback is saved for the authorities.')}catch(e){say($('#restroom-out'),e.message,'err')}};
api('/api/config').then(c=>$('#mode').textContent=`signals: ${c.signal_mode}`);

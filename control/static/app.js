const $=(s,r=document)=>r.querySelector(s),$$=(s,r=document)=>[...r.querySelectorAll(s)];
const icon=n=>'<svg aria-hidden="true"><use href="/icons.svg#icon-'+n+'"/></svg>';
const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const clock=v=>{const n=Math.max(0,Number(v)||0);return Math.floor(n/60)+":"+String(Math.floor(n%60)).padStart(2,"0")};
const saved=[10,20,50,100].includes(+localStorage.getItem("snaproomPageSize"))?+localStorage.getItem("snaproomPageSize"):10;
const model={player:{state:"stop",song:{}},snapcast:{streams:[],groups:[]},queue:[],playlists:[],library:{items:[],total:0},config:{path:"music",directories:[]},view:"albums",folder:"",query:"",page:0,pageSize:saved,lyrics:null,artUri:"",playlistName:""};
let toastTimer,searchTimer,pollTimer,dragValue=null,playerButtonIcon="",snapcastSignature="",playlistSignature="",playlistLoadToken=0;

async function request(url,options={}){
  const response=await fetch(url,options),type=response.headers.get("content-type")||"";
  const data=type.includes("json")?await response.json():await response.text();
  if(!response.ok||data?.ok===false)throw new Error(data?.error||("HTTP "+response.status));
  return data;
}
const post=(url,data)=>request(url,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(data)});
function toast(message,error=false,duration=2800){const n=$("#toast");n.textContent=message;n.className="toast show"+(error?" error":"");clearTimeout(toastTimer);toastTimer=setTimeout(()=>n.className="toast",duration)}
async function action(name,extra={},quiet=false){try{await post("/api/player/action",{action:name,...extra});await refreshCollections();await refreshState();if(!quiet)toast("操作完成")}catch(e){toast(e.message,true)}}
const artUrl=uri=>uri?"/api/player/art?uri="+encodeURIComponent(uri):"";
const artHTML=(uri,title)=>'<span class="cover-mark">SR</span>'+(uri?'<img src="'+artUrl(uri)+'" alt="'+esc(title)+'" loading="lazy" onerror="this.remove()">':"");

async function bootstrap(){
  $("#pageSize").value=String(model.pageSize);
  try{const d=await request("/api/player/bootstrap?limit="+model.pageSize);Object.assign(model,{player:d.player,queue:d.queue,playlists:d.playlists,config:d.libraryConfig});renderConfig();renderQueue();renderPlaylists();await Promise.all([loadLibrary(0),refreshState()])}
  catch(e){toast(e.message,true);$("#speakerList").innerHTML='<p class="empty">'+esc(e.message)+"</p>"}
}
async function refreshState(){
  try{const d=await request("/api/state");model.player=d.player||d.dlna||model.player;model.snapcast=d.snapcast||model.snapcast;$("#healthLamp").classList.toggle("ok",!d.errors?.length);$("#healthText").textContent=d.errors?.length?"部分异常":"服务在线";renderPlayer();renderSnapcast()}
  catch{$("#healthLamp").classList.remove("ok");$("#healthText").textContent="连接中断"}
}
async function refreshCollections(){try{const d=await request("/api/player/collections");model.queue=d.queue;model.playlists=d.playlists;renderQueue();renderPlaylists()}catch(e){toast(e.message,true)}}
async function loadLibrary(page=0){
  const offset=Math.max(0,page)*model.pageSize;
  try{model.library=await request("/api/player/library?view="+model.view+"&q="+encodeURIComponent(model.query)+"&offset="+offset+"&limit="+model.pageSize+"&parent="+encodeURIComponent(model.folder));model.page=Math.max(0,page);renderLibrary()}
  catch(e){toast(e.message,true)}
}
function activeSource(){
  const s=model.snapcast.streams||[];
  return s.find(x=>/airplay/i.test(x.id)&&x.status==="playing")||s.find(x=>/dlna/i.test(x.id)&&x.status==="playing")||s.find(x=>x.status==="playing")||s.find(x=>/default/i.test(x.id))||s[0]||{id:"Default",status:"idle"};
}
const airplayActive=()=>/airplay/i.test(activeSource().id)&&activeSource().status==="playing";
function renderPlayer(){
  const p=model.player||{},song=p.song||{},external=airplayActive(),title=external?"AirPlay 正在播放":song.title||"未播放";
  const meta=external?"外部音源 · 播放由 iPhone 控制":([song.artist,song.album].filter(Boolean).join(" · ")||"LOCAL / DLNA");
  ["#trackTitle","#drawerTitle"].forEach(id=>$(id).textContent=title);["#trackMeta","#drawerMeta"].forEach(id=>$(id).textContent=meta);
  $("#playSourceLabel").textContent=external?"AIRPLAY":song.file?.startsWith("http")?"DLNA":"LOCAL / DLNA";
  const nextButtonIcon=!external&&p.state==="play"?"pause":"play-filled";if(nextButtonIcon!==playerButtonIcon){$("#playToggle").innerHTML=icon(nextButtonIcon);playerButtonIcon=nextButtonIcon}
  $$("[data-action='previous'],[data-action='next'],#seek").forEach(n=>n.disabled=external);
  $("#seek").max=Math.max(1,+p.duration||1);$("#seek").value=Math.min(+p.elapsed||0,+$("#seek").max);$("#elapsed").textContent=clock(p.elapsed);$("#duration").textContent=clock(p.duration);
  $("#playerVolume").value=Math.max(0,p.volume??0);$("#playerVolumeValue").textContent=p.volume>=0?p.volume:"--";$("#random").classList.toggle("on",!!p.random);$("#repeat").classList.toggle("on",!!p.repeat);
  const uri=external?"":song.file||"";if(uri!==model.artUri){model.artUri=uri;setPlayerArt(uri,title);loadLyrics(uri)}updateLyrics(+p.elapsed||0);
}
function setPlayerArt(uri,title){
  $("#heroArt").innerHTML=uri?'<img src="'+artUrl(uri)+'" alt="'+esc(title)+'" crossorigin="anonymous">':"<span>SR</span>";
  $("#miniArt").innerHTML=uri?'<img src="'+artUrl(uri)+'" alt="">':"<i>SR</i>";
  const image=$("#heroArt img");if(image){image.onerror=()=>image.remove();image.onload=()=>extractAccent(image)}
}
function extractAccent(image){try{const c=document.createElement("canvas"),x=c.getContext("2d",{willReadFrequently:true});c.width=c.height=1;x.drawImage(image,0,0,1,1);const d=x.getImageData(0,0,1,1).data;document.documentElement.style.setProperty("--accent","rgb("+Math.max(75,d[0])+" "+Math.max(65,d[1])+" "+Math.max(55,d[2])+")")}catch{}}
async function loadLyrics(uri){
  if(!uri||uri.startsWith("http")){model.lyrics=null;$("#lyrics").innerHTML="<p>外部音源暂无本地歌词</p>";return}
  try{model.lyrics=await request("/api/player/lyrics?uri="+encodeURIComponent(uri));renderLyrics()}catch{model.lyrics=null;$("#lyrics").innerHTML="<p>暂无歌词</p>"}
}
function renderLyrics(){const b=$("#lyrics"),d=model.lyrics;if(!d||d.kind==="none"){b.innerHTML="<p>暂无歌词</p>";return}b.innerHTML=d.kind==="synced"?d.lines.map((l,i)=>'<p data-time="'+l.time+'" data-line="'+i+'">'+esc(l.text||"♪")+"</p>").join(""):"<p>"+esc(d.text).replace(/\n/g,"<br>")+"</p>"}
function updateLyrics(elapsed){if(model.lyrics?.kind!=="synced")return;const lines=$$("#lyrics [data-time]");let current;for(const line of lines){if(+line.dataset.time<=elapsed)current=line;else break}lines.forEach(n=>n.classList.toggle("active",n===current));if(current&&current.dataset.line!==model.activeLyric){model.activeLyric=current.dataset.line;current.scrollIntoView({block:"center",behavior:"smooth"})}}

function renderSnapcast(){
  const streams=model.snapcast.streams||[],groups=model.snapcast.groups||[],source=activeSource();
  $("#activeSourceName").textContent=source.id;$("#activeSourceState").textContent=source.status==="playing"?"正在播放":source.status==="idle"?"等待音频":"已连接";
  const signature=JSON.stringify({streams:streams.map(s=>[s.id,s.status]),groups:groups.map(g=>[g.streamId,g.clients.map(c=>[c.id,c.name,c.ip,c.connected,c.volume,c.muted,c.latency])])});if(signature===snapcastSignature)return;
  snapcastSignature=signature;
  $("#sourceList").innerHTML=streams.map(s=>'<button class="source-pill '+(groups.length&&groups.every(g=>g.streamId===s.id)?"active":"")+'" data-stream="'+esc(s.id)+'"><i></i>'+esc(s.id)+"</button>").join("");
  const list=$("#speakerList"),expanded=new Set($$(".speaker-card details[open]",list).map(n=>n.closest(".speaker-card").dataset.clientId));list.replaceChildren();groups.forEach(g=>g.clients.forEach(c=>list.append(speakerCard(c,expanded.has(String(c.id))))));if(!list.children.length)list.innerHTML='<p class="empty">未发现在线音箱</p>';
}
function speakerCard(c,expanded=false){
  const n=document.createElement("article");n.className="speaker-card";n.dataset.clientId=c.id;
  n.innerHTML='<header><div class="speaker-title"><span class="dot '+(c.connected?"":"off")+'"></span><b>'+esc(c.name)+"</b><small>"+esc(c.ip)+" · "+(c.connected?"在线":"离线")+'</small></div><button class="icon-btn mute" aria-label="静音">'+icon(c.muted?"mute":"volume")+'</button></header><details class="device-controls" '+(expanded?"open":"")+'><summary><span>'+icon("expand")+'调节</span><output><b>'+c.volume+'</b>% · <b>'+c.latency+'</b> ms</output></summary><div class="device-control-body"><label class="volume-row">'+icon("volume")+'<input class="speaker-volume" type="range" min="0" max="100" value="'+c.volume+'"><output>'+c.volume+'</output></label><div class="latency"><div class="latency-head"><span>延迟补偿 · 向右加快</span><output>'+c.latency+' ms</output></div><input class="latency-range" type="range" min="-500" max="500" step="10" dir="rtl" value="'+Math.max(-500,Math.min(500,c.latency))+'"><div class="latency-editor"><button data-step="10" aria-label="声音减慢">＋</button><button data-zero aria-label="延迟归零">'+icon("reset")+'</button><label class="number-wrap"><input class="latency-number" type="number" min="-1000" max="5000" step="10" value="'+c.latency+'"><span>ms</span></label><button data-step="-10" aria-label="声音加快">−</button></div></div></div></details>';
  const volume=$(".speaker-volume",n),out=$(".volume-row output",n),mute=$(".mute",n),range=$(".latency-range",n),number=$(".latency-number",n),live=$(".latency-head output",n);
  volume.oninput=()=>out.textContent=volume.value;volume.onchange=()=>snap("/api/snapcast/volume",{clientId:c.id,percent:+volume.value,muted:false});mute.onclick=()=>snap("/api/snapcast/volume",{clientId:c.id,percent:c.volume,muted:!c.muted});
  range.oninput=()=>{number.value=range.value;live.textContent=range.value+" ms"};range.onchange=()=>setLatency(c.id,+range.value,range,number,live);number.onchange=()=>setLatency(c.id,+number.value,range,number,live);
  $$("[data-step]",n).forEach(b=>b.onclick=()=>setLatency(c.id,+number.value + +b.dataset.step,range,number,live));$("[data-zero]",n).onclick=()=>setLatency(c.id,0,range,number,live);return n;
}
async function snap(url,data){try{await post(url,data);toast("已保存");setTimeout(refreshState,200)}catch(e){toast(e.message,true)}}
function setLatency(id,value,range,number,live){value=Math.max(-1000,Math.min(5000,Math.round(value/10)*10));number.value=value;range.value=Math.max(-500,Math.min(500,value));live.textContent=value+" ms";snap("/api/snapcast/latency",{clientId:id,latency:value})}

function trackRow(song,index,context="library"){
  const n=document.createElement("article"),sortable=context==="queue"||context==="playlist";n.className="track-row";n.dataset.uri=song.file;n.dataset.id=song.id??"";n.dataset.position=song.pos??song.playlistPos??index;
  n.innerHTML='<button class="drag-handle" aria-label="'+(sortable?"拖动排序":"曲目序号")+'" '+(sortable?'draggable="true"':"")+'>'+(sortable?icon("drag"):"<span>"+String(index+1).padStart(2,"0")+"</span>")+'</button><div class="track-copy"><b>'+esc(song.title)+"</b><small>"+esc([song.artist,song.album].filter(Boolean).join(" · "))+"</small></div><time>"+clock(song.duration)+'</time><div class="row-actions"><button data-play aria-label="立即播放">'+icon("play")+'</button><button data-next aria-label="下一首播放">'+icon("next")+"</button>"+(sortable?'<button data-remove aria-label="移除">'+icon("trash")+'<span class="fallback">×</span></button>':"")+"</div>";
  $("[data-play]",n).onclick=()=>action("play-now",{uri:song.file});$("[data-next]",n).onclick=()=>action("add-next",{uri:song.file});
  const remove=$("[data-remove]",n);if(remove)remove.onclick=()=>context==="playlist"?editPlaylist("playlist-remove",{position:+n.dataset.position}):action("remove",{id:+n.dataset.id});
  if(sortable){
    const moveTo=target=>{if(dragValue===null||dragValue===target)return;context==="queue"?action("move",{id:dragValue,position:target}):editPlaylist("playlist-move",{from:dragValue,to:target});dragValue=null};
    n.ondragstart=()=>dragValue=context==="queue"?+n.dataset.id:+n.dataset.position;n.ondragover=e=>e.preventDefault();n.ondrop=()=>moveTo(+n.dataset.position);
    const handle=$(".drag-handle",n);handle.ontouchstart=()=>{dragValue=context==="queue"?+n.dataset.id:+n.dataset.position;n.dataset.touchTarget=n.dataset.position};handle.ontouchmove=e=>{e.preventDefault();const t=e.touches[0],row=document.elementFromPoint(t.clientX,t.clientY)?.closest(".track-row");if(row)n.dataset.touchTarget=row.dataset.position};handle.ontouchend=()=>moveTo(+n.dataset.touchTarget);
  }
  return n;
}
function renderQueue(){const list=$("#queueList");list.replaceChildren();model.queue.forEach((s,i)=>list.append(trackRow(s,i,"queue")));if(!list.children.length)list.innerHTML='<p class="empty">队列为空</p>';$("#queueCount").textContent=model.queue.length}
function renderPlaylists(){
  $("#playlistCount").textContent=model.playlists.length;const signature=JSON.stringify(model.playlists);if(signature===playlistSignature)return;playlistSignature=signature;
  const tabs=$("#playlistTabs");tabs.replaceChildren();if(!model.playlists.includes(model.playlistName))model.playlistName=model.playlists[0]||"";
  model.playlists.forEach(name=>{const b=document.createElement("button");b.type="button";b.className=name===model.playlistName?"active":"";b.innerHTML=icon("playlist")+'<span>'+esc(name)+'</span>';b.onclick=()=>selectPlaylist(name);tabs.append(b)});
  if(model.playlistName)selectPlaylist(model.playlistName,true);else clearPlaylistPage();
}
function clearPlaylistPage(){$("#playlistPageTitle").textContent="请选择歌单";$("#playlistPageActions").replaceChildren();$("#playlistPageTracks").innerHTML='<p class="empty">暂无歌单，导入或从队列保存一个</p>'}
async function selectPlaylist(name,force=false){
  if(!force&&name===model.playlistName&&$("#playlistPageTracks").children.length)return;model.playlistName=name;$$('.playlist-tabs button').forEach((b,i)=>b.classList.toggle("active",model.playlists[i]===name));
  const token=++playlistLoadToken,title=$("#playlistPageTitle"),body=$("#playlistPageTracks"),actions=$("#playlistPageActions");title.textContent=name;actions.replaceChildren();body.innerHTML='<p class="empty">正在读取…</p>';
  try{const d=await request("/api/player/playlist?name="+encodeURIComponent(name));if(token!==playlistLoadToken)return;actions.innerHTML='<button data-pl-play>'+icon("play")+'播放</button><button class="secondary" data-pl-append>追加</button><button class="secondary" data-pl-rename>'+icon("edit")+'重命名</button><button class="secondary" data-pl-export>'+icon("export")+'导出</button><button class="secondary danger" data-pl-delete>'+icon("trash")+'<span class="fallback">×</span></button>';body.replaceChildren();d.tracks.forEach((s,i)=>body.append(trackRow(s,i,"playlist")));if(!body.children.length)body.innerHTML='<p class="empty">歌单为空</p>';
    $("[data-pl-play]",actions).onclick=()=>action("playlist-load",{name});$("[data-pl-append]",actions).onclick=()=>action("playlist-load",{name,append:true,play:false});$("[data-pl-export]",actions).onclick=()=>location.href="/api/player/playlist-export?name="+encodeURIComponent(name);$("[data-pl-delete]",actions).onclick=()=>confirm("删除歌单“"+name+"”？")&&deletePlaylist(name);$("[data-pl-rename]",actions).onclick=()=>renamePlaylist(name);
  }catch(e){if(token===playlistLoadToken)body.innerHTML='<p class="empty">'+esc(e.message)+'</p>';toast(e.message,true)}
}
async function renamePlaylist(name){const next=prompt("新歌单名称",name)?.trim();if(!next||next===name)return;try{await post("/api/player/action",{action:"playlist-rename",name,newName:next});model.playlistName=next;playlistSignature="";await refreshCollections();toast("歌单已更新")}catch(e){toast(e.message,true)}}
async function deletePlaylist(name){try{await post("/api/player/action",{action:"playlist-delete",name});model.playlistName="";playlistSignature="";await refreshCollections();toast("歌单已删除")}catch(e){toast(e.message,true)}}
async function editPlaylist(name,extra){try{await post("/api/player/action",{action:name,name:model.playlistName,...extra});playlistSignature="";await refreshCollections();toast("歌单已更新")}catch(e){toast(e.message,true)}}

function renderLibrary(){
  const list=$("#libraryList");list.replaceChildren();list.className="library-content";
  if(model.view==="albums"||model.view==="artists"){list.classList.add(model.view==="albums"?"album-grid":"artist-grid");model.library.items.forEach(item=>{const n=document.createElement("button"),art=item.artUri||(item.artUris||[])[0];n.className="media-card";n.innerHTML='<span class="cover">'+artHTML(art,item.title)+"</span><h3>"+esc(item.title)+"</h3><p>"+esc(item.artist||((item.albumCount||0)+" 张专辑 · "+item.count+" 首"))+"</p>";n.onclick=()=>openLibraryDetail(item.kind,item.id);list.append(n)})}
  else model.library.items.forEach((item,i)=>{if(item.kind==="folder"){const n=document.createElement("article");n.className="track-row";n.innerHTML='<span class="drag-handle">'+icon("folder")+'</span><div class="track-copy"><b>'+esc(item.title)+"</b><small>"+esc(item.path)+'</small></div><span></span><button class="icon-btn">'+icon("chevron-right")+"</button>";n.onclick=()=>{model.folder=item.path;loadLibrary(0)};list.append(n)}else list.append(trackRow(item,i))});
  if(!list.children.length)list.innerHTML='<p class="empty">'+(model.query?"没有匹配结果":"曲库为空")+"</p>";
  $("#libraryCount").textContent=model.library.total;const pages=Math.max(1,Math.ceil(model.library.total/model.pageSize));$("#pageInfo").textContent=(model.page+1)+" / "+pages;$("#prevPage").disabled=model.page===0;$("#nextPage").disabled=model.page+1>=pages;
  const trail=$("#folderTrail");trail.hidden=model.view!=="folders";if(!trail.hidden){trail.innerHTML='<button data-root>曲库根目录</button>'+(model.folder?" / "+esc(model.folder):"");$("[data-root]",trail).onclick=()=>{model.folder="";loadLibrary(0)}}
}
async function openLibraryDetail(kind,id){
  try{const d=await request("/api/player/library-detail?kind="+kind+"&id="+encodeURIComponent(id));$("#detailEyebrow").textContent=kind==="album"?"ALBUM":"ARTIST";$("#detailTitle").textContent=d.title;const tracks=d.tracks||[],art=d.artUri||d.albums?.[0]?.artUri;$("#detailBody").innerHTML='<div class="detail-hero"><span class="cover">'+artHTML(art,d.title)+'</span><div><p>'+esc(d.artist||((d.albums?.length||0)+" 张专辑"))+'</p><div class="dialog-actions"><button data-all-play>'+icon("play")+'播放全部</button><button class="secondary" data-all-add>加入队列</button></div></div></div><div class="track-list" id="detailTracks"></div>';const list=$("#detailTracks"),all=kind==="artist"?d.albums.flatMap(a=>a.tracks):tracks;if(kind==="artist")d.albums.forEach(a=>{const h=document.createElement("h3");h.textContent=a.title;list.append(h);a.tracks.forEach((s,i)=>list.append(trackRow(s,i)))});else tracks.forEach((s,i)=>list.append(trackRow(s,i)));$("[data-all-play]").onclick=()=>action("play-many",{uris:all.map(t=>t.file)});$("[data-all-add]").onclick=()=>action("add-many",{uris:all.map(t=>t.file)});$("#detailDialog").showModal()}catch(e){toast(e.message,true)}
}
function renderConfig(){$("#libraryPath").value=model.config.path||"music";$("#libraryPaths").innerHTML=(model.config.directories||[]).map(p=>'<option value="'+esc(p)+'"></option>').join("")}
async function loadServerPlaylists(){const list=$("#serverPlaylistList");list.innerHTML='<p class="empty">正在扫描…</p>';try{const d=await request("/api/player/playlist-files");list.replaceChildren();d.items.forEach(item=>{const n=document.createElement("button");n.className="server-file";n.innerHTML="<span><b>"+esc(item.name)+"</b><small>"+esc(item.hostPath)+"</small></span><em>导入</em>";n.onclick=()=>importServer(item);list.append(n)});if(!list.children.length)list.innerHTML='<p class="empty">未找到 M3U、M3U8 或 PLS</p>'}catch(e){list.innerHTML='<p class="empty">'+esc(e.message)+"</p>"}}
async function importServer(item){try{const d=await post("/api/player/action",{action:"playlist-import-server",path:item.path,name:item.name});await refreshCollections();$("#importDialog").close();reportImport(d.result)}catch(e){toast(e.message,true)}}
function reportImport(r){const skipped=r.skipped?"，跳过 "+r.skipped+" 首"+(r.skippedExamples?.length?"："+r.skippedExamples.slice(0,2).join("；"):""):"";toast("已导入 "+r.count+" 首"+skipped,false,6000)}

document.addEventListener("click",e=>{
  const tab=e.target.closest("[data-tab]");if(tab){$$("[data-tab]").forEach(n=>n.classList.toggle("active",n===tab));$$("[data-panel]").forEach(n=>n.classList.toggle("active",n.dataset.panel===tab.dataset.tab));if(["queue","playlists"].includes(tab.dataset.tab))refreshCollections();if(tab.dataset.tab==="library")loadLibrary(model.page);return}
  const source=e.target.closest("[data-stream]");if(source)snap("/api/snapcast/all-stream",{streamId:source.dataset.stream});
  const control=e.target.closest("[data-action]");if(control){const name=control.dataset.action;if(name==="toggle")action(model.player.state==="play"?"pause":"resume",{},true);else action(name,{},true)}
  const close=e.target.closest("[data-close-dialog]");if(close)close.closest("dialog").close();
});
$$("[data-library-view]").forEach(b=>b.onclick=()=>{$$("[data-library-view]").forEach(n=>n.classList.toggle("active",n===b));model.view=b.dataset.libraryView;model.folder="";loadLibrary(0)});
$("#seek").onchange=e=>action("seek",{seconds:Math.round(+e.target.value)},true);$("#playerVolume").oninput=e=>$("#playerVolumeValue").textContent=e.target.value;$("#playerVolume").onchange=e=>action("volume",{value:+e.target.value},true);$("#playerMute").onclick=()=>action("volume",{value:model.player.volume===0?50:0},true);
$("#random").onclick=()=>action("random",{enabled:!model.player.random},true);$("#repeat").onclick=()=>action("repeat",{enabled:!model.player.repeat},true);$("#clearQueue").onclick=()=>confirm("清空当前播放队列？")&&action("clear");
$("#search").oninput=e=>{model.query=e.target.value;clearTimeout(searchTimer);searchTimer=setTimeout(()=>loadLibrary(0),260)};$("#pageSize").onchange=e=>{model.pageSize=+e.target.value;localStorage.setItem("snaproomPageSize",model.pageSize);loadLibrary(0)};$("#prevPage").onclick=()=>loadLibrary(model.page-1);$("#nextPage").onclick=()=>loadLibrary(model.page+1);
$("#scanButton").onclick=async()=>{await action("update-library",{},true);toast("正在扫描曲库");setTimeout(()=>loadLibrary(0),1800)};$("#refreshRooms").onclick=refreshState;
$("#savePlaylist").onclick=()=>{const name=$("#playlistName").value.trim();name?action("playlist-save",{name,overwrite:true}):toast("请输入歌单名称",true)};
$("#importPlaylistButton").onclick=()=>{$("#importDialog").showModal();loadServerPlaylists()};$("#chooseLocalPlaylist").onclick=()=>$("#playlistFile").click();$("#refreshPlaylistFiles").onclick=loadServerPlaylists;
$("#playlistFile").onchange=async e=>{const file=e.target.files[0];if(!file)return;if(file.size>1048576){toast("歌单不能超过 1 MB",true);return}try{const d=await post("/api/player/action",{action:"playlist-import",name:file.name.replace(/\.(m3u8?|pls)$/i,"").slice(0,80),content:await file.text(),overwrite:true});await refreshCollections();$("#importDialog").close();reportImport(d.result)}catch(error){toast(error.message,true)}finally{e.target.value=""}};
$("#libraryForm").onsubmit=async e=>{e.preventDefault();try{const d=await post("/api/player/library-config",{path:$("#libraryPath").value});model.config=d.result;renderConfig();toast("曲库目录已保存，正在扫描");setTimeout(()=>loadLibrary(0),1800)}catch(error){toast(error.message,true)}};
$("#openPlayer").onclick=()=>$("#nowPlayingPanel").classList.add("open");$("#closePlayer").onclick=()=>$("#nowPlayingPanel").classList.remove("open");
bootstrap();pollTimer=setInterval(refreshState,2000);document.addEventListener("visibilitychange",()=>{clearInterval(pollTimer);if(!document.hidden){refreshState();pollTimer=setInterval(refreshState,2000)}});

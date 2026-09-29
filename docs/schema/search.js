(function(){
  var box=document.getElementById('q'),out=document.getElementById('res'),base=document.body.dataset.root||'';
  if(!box||!window.SR_INDEX)return;
  var sel=-1;
  function render(){
    var q=box.value.trim().toLowerCase();out.innerHTML='';sel=-1;if(!q)return;
    var hits=[];
    for(var i=0;i<SR_INDEX.length&&hits.length<40;i++){
      var e=SR_INDEX[i],k=e[0].toLowerCase(),p=k.indexOf(q);
      if(p>=0)hits.push([p===0?0:(k.charAt(p-1).match(/[^a-z0-9]/)?1:2),e]);
    }
    hits.sort(function(a,b){return a[0]-b[0]||a[1][0].length-b[1][0].length});
    hits.forEach(function(h){var e=h[1],li=document.createElement('li'),a=document.createElement('a');
      a.href=base+e[1];a.textContent=e[0];var s=document.createElement('small');s.textContent=e[2];a.appendChild(s);
      li.appendChild(a);out.appendChild(li)});
  }
  function move(d){var as=out.querySelectorAll('a');if(!as.length)return;if(sel>=0)as[sel].classList.remove('sel');
    sel=(sel+d+as.length)%as.length;as[sel].classList.add('sel');as[sel].scrollIntoView({block:'nearest'})}
  box.addEventListener('input',render);
  box.addEventListener('keydown',function(ev){
    if(ev.key==='ArrowDown'){move(1);ev.preventDefault()}else if(ev.key==='ArrowUp'){move(-1);ev.preventDefault()}
    else if(ev.key==='Enter'){var as=out.querySelectorAll('a');var a=as[sel>=0?sel:0];if(a)location.href=a.href}
    else if(ev.key==='Escape'){box.value='';render()}});
  document.addEventListener('keydown',function(ev){if(ev.key==='/'&&document.activeElement!==box){box.focus();ev.preventDefault()}});
  document.addEventListener('click',function(ev){if(!ev.target.closest('.search'))out.innerHTML=''});
})();

function initWorkspace(){
  document.body.addEventListener("htmx:configRequest",function(event){
    var csrf=document.querySelector('meta[name="csrf-token"]');
    if(csrf){event.detail.headers["X-CSRFToken"]=csrf.content}
  });
  var side=document.getElementById("side");
  var menu=document.getElementById("menu");
  var feed=document.getElementById("feed");
  var q=document.getElementById("q");
  var conversationId=document.getElementById("conversation-id");
  document.body.addEventListener("htmx:afterSwap",function(event){
    if(event.target.id!=="feed")return;
    var bubble=event.target.lastElementChild;
    if(bubble&&bubble.dataset.conversationId&&conversationId){
      conversationId.value=bubble.dataset.conversationId;
    }
    var intro=document.getElementById("intro");
    if(intro)intro.remove();
    if(q){q.value="";q.style.height="auto";q.focus()}
  });
  if(menu&&side){
    menu.onclick=function(){side.classList.toggle("open")};
    if(feed){feed.addEventListener("click",function(){side.classList.remove("open")})}
  }
  if(q){
    var autosize=function(){
      q.style.height="auto";
      var capped=Math.min(q.scrollHeight,140);
      q.style.height=capped+"px";
      if(q.scrollHeight>capped){q.scrollTop=q.scrollHeight}
    };
    q.addEventListener("input",autosize);
    autosize();
  }
  var nbSel=document.getElementById("nb-select");
  var panel=document.getElementById("nb-panel");
  if(nbSel&&panel){
    var closePanel=function(){nbSel.setAttribute("aria-expanded","false")};
    nbSel.onclick=function(e){
      e.stopPropagation();
      var open=nbSel.getAttribute("aria-expanded")==="true";
      nbSel.setAttribute("aria-expanded",open?"false":"true");
    };
    document.addEventListener("click",function(e){
      if(!panel.contains(e.target)&&e.target!==nbSel)closePanel();
    });
    window.addEventListener("keydown",function(e){if(e.key==="Escape")closePanel()});
  }
  var said=document.getElementById("nb-new-dialog");
  if(nbSel&&said){said.querySelector("form").addEventListener("submit",function(){said.close()})}
  var plus=document.getElementById("nb-plus");
  if(plus&&said){
    plus.onclick=function(){said.showModal()};
    said.addEventListener("click",function(e){if(e.target===said)said.close()});
    window.addEventListener("keydown",function(e){if(e.key==="Escape")said.close()});
  }
  var up=document.getElementById("up");
  var file=document.getElementById("file");
  if(up&&file){
    up.onclick=function(){file.click()};
  }
}
document.addEventListener("DOMContentLoaded",initWorkspace);

function initWorkspace(){
  var side=document.getElementById("side");
  var menu=document.getElementById("menu");
  var feed=document.getElementById("feed");
  var q=document.getElementById("q");
  if(menu&&side){
    menu.onclick=function(){side.classList.toggle("open")};
    if(feed){feed.addEventListener("click",function(){side.classList.remove("open")})}
  }
  if(q){
    var autosize=function(){q.style.height="auto";q.style.height=Math.min(q.scrollHeight,140)+"px"};
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
}
document.addEventListener("DOMContentLoaded",initWorkspace);

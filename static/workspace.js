function initWorkspace(){
  document.body.addEventListener("htmx:configRequest",function(event){
    var csrf=document.querySelector('meta[name="csrf-token"]');
    if(csrf){event.detail.headers["X-CSRFToken"]=csrf.content}
  });
  var side=document.getElementById("side");
  var menu=document.getElementById("menu");
  var feed=document.getElementById("feed");
  var jumpLatest=document.getElementById("jump-latest");
  var q=document.getElementById("q");
  var conversationId=document.getElementById("conversation-id");
  var askForm=document.getElementById("ask-form");
  var isNearLiveEdge=function(){
    return feed.scrollHeight-feed.scrollTop-feed.clientHeight<96;
  };
  var updateJumpLatest=function(){
    if(jumpLatest)jumpLatest.hidden=isNearLiveEdge();
  };
  var scrollToLiveEdge=function(smooth){
    feed.scrollTo({
      top:feed.scrollHeight,
      behavior:smooth?"smooth":"auto"
    });
    updateJumpLatest();
  };
  if(feed){
    feed.addEventListener("scroll",updateJumpLatest);
    updateJumpLatest();
  }
  if(jumpLatest){
    jumpLatest.addEventListener("click",function(){
      scrollToLiveEdge(true);
      if(q)q.focus();
    });
  }
  if(askForm&&q&&feed){
    askForm.addEventListener("submit",function(event){
      event.preventDefault();
      var question=q.value.trim();
      if(!question)return;
      var send=document.getElementById("send");
      send.disabled=true;
      var body=new FormData(askForm);
      body.set("stream","true");
      var csrf=document.querySelector('meta[name="csrf-token"]');
      fetch(askForm.action,{method:"POST",headers:{"X-CSRFToken":csrf?csrf.content:""},body:body})
        .then(function(response){
          if(!response.ok)throw new Error("Chat request failed");
          var reader=response.body.getReader();
          var decoder=new TextDecoder();
          var buffer="";
          var assistant=null;
          var streamFollow=true;
          var pendingHtml=null;
          var renderTimer=null;
          // Keep the provider fast; pace only the visible browser updates.
          var streamRenderInterval=70;
          var fadeLatestToken=function(root){
            var walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);
            var latest=null;
            while(walker.nextNode()){
              if(walker.currentNode.nodeValue.trim())latest=walker.currentNode;
            }
            if(!latest)return;
            var start=latest.nodeValue.search(/\S+\s*$/);
            if(start<0)return;
            var token=latest.splitText(start);
            var fade=document.createElement("span");
            fade.className="stream-token";
            fade.textContent=token.nodeValue;
            token.parentNode.replaceChild(fade,token);
          };
          var scrollStreamAsItGrows=function(){
            if(!assistant||!streamFollow)return;
            var feedBottom=feed.getBoundingClientRect().bottom-24;
            var answerBottom=assistant.getBoundingClientRect().bottom;
            if(answerBottom>feedBottom){
              feed.scrollTop+=answerBottom-feedBottom;
            }
          };
          var stopStreamFollowing=function(){streamFollow=false};
          var cleanupStreamFollowing=function(){
            feed.removeEventListener("wheel",stopStreamFollowing);
            feed.removeEventListener("touchstart",stopStreamFollowing);
          };
          feed.addEventListener("wheel",stopStreamFollowing,{once:true});
          feed.addEventListener("touchstart",stopStreamFollowing,{once:true});
          var renderAssistant=function(){
            if(!assistant||pendingHtml===null)return;
            assistant.innerHTML=pendingHtml;
            fadeLatestToken(assistant);
            pendingHtml=null;
            scrollStreamAsItGrows();
            if(!streamFollow&&isNearLiveEdge())scrollToLiveEdge();
            else updateJumpLatest();
          };
          var scheduleAssistantRender=function(html){
            pendingHtml=html;
            if(renderTimer!==null)return;
            renderTimer=window.setTimeout(function(){
              renderTimer=null;
              renderAssistant();
            },streamRenderInterval);
          };
          var flushAssistantRender=function(){
            if(renderTimer!==null){
              window.clearTimeout(renderTimer);
              renderTimer=null;
            }
            renderAssistant();
          };
          function read(){
            return reader.read().then(function(result){
              if(result.done){
                flushAssistantRender();
                cleanupStreamFollowing();
                send.disabled=false;
                return;
              }
              buffer+=decoder.decode(result.value,{stream:true});
              var events=buffer.split("\n\n");
              buffer=events.pop();
              events.forEach(function(raw){
                var eventName="message", dataLine=raw.split("\n").find(function(line){return line.indexOf("data:")===0});
                var eventLine=raw.split("\n").find(function(line){return line.indexOf("event:")===0});
                if(eventLine)eventName=eventLine.slice(6).trim();
                if(!dataLine)return;
                var data=JSON.parse(dataLine.slice(5).trim());
                if(eventName==="user"){
                  var intro=document.getElementById("intro");
                  if(intro)intro.remove();
                  var userBubble=document.createElement("div");
                  userBubble.className="msg user";
                  userBubble.textContent=data.text;
                  feed.appendChild(userBubble);
                  conversationId.value=data.conversation_id;
                  assistant=document.createElement("div");
                  assistant.className="msg ai message-loading";
                  var spinner=document.createElement("span");
                  spinner.className="message-spinner";
                  spinner.setAttribute("aria-label","Gemini is thinking");
                  assistant.appendChild(spinner);
                  var status=document.createElement("span");
                  status.className="thinking-status";
                  status.setAttribute("role","status");
                  status.textContent="thinking\u2026";
                  assistant.appendChild(status);
                  feed.appendChild(assistant);
                  feed.scrollTop=Math.max(0,assistant.offsetTop-24);
                  updateJumpLatest();
                }else if(eventName==="message"&&assistant){
                  if(assistant.classList.contains("message-loading")){
                    assistant.classList.remove("message-loading");
                    assistant.textContent="";
                  }
                  scheduleAssistantRender(data.html);
                }else if(eventName==="error"){
                  cleanupStreamFollowing();
                  if(renderTimer!==null){
                    window.clearTimeout(renderTimer);
                    renderTimer=null;
                  }
                  pendingHtml=null;
                  if(assistant)assistant.classList.remove("message-loading");
                  if(assistant)assistant.textContent=data.message;
                  else{assistant=document.createElement("div");assistant.className="msg ai err";assistant.textContent=data.message;feed.appendChild(assistant)}
                  if(assistant)assistant.classList.add("err");
                  send.disabled=false;
                }
              });
              return read();
            });
          }
          return read();
        })
        .catch(function(error){
          cleanupStreamFollowing();
          var failure=document.createElement("div");
          failure.className="msg ai";
          failure.textContent=error.message;
          feed.appendChild(failure);
          send.disabled=false;
        });
      q.value="";q.style.height="auto";
    });
    // Enter sends the message; Ctrl/Cmd/Shift+Enter keeps the browser's
    // newline behaviour. preventDefault stops the newline AFTER sending.
    q.addEventListener("keydown",function(event){
      if(event.key!=="Enter"||event.isComposing)return;
      if(event.shiftKey||event.ctrlKey||event.metaKey||event.altKey)return;
      event.preventDefault();
      if(askForm.requestSubmit){askForm.requestSubmit()}
      else{askForm.dispatchEvent(new Event("submit",{cancelable:true}))}
    });
  }
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

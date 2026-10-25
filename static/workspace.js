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
  var askForm=document.getElementById("ask-form");
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
          function read(){
            return reader.read().then(function(result){
              if(result.done){send.disabled=false;return}
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
                  feed.appendChild(assistant);
                }else if(eventName==="message"&&assistant){
                  if(assistant.classList.contains("message-loading")){
                    assistant.classList.remove("message-loading");
                    assistant.textContent="";
                  }
                  assistant.innerHTML=data.html;
                  feed.scrollTop=feed.scrollHeight;
                }else if(eventName==="error"){
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

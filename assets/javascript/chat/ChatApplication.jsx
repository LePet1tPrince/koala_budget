'use strict';
import React, {useState, useEffect} from "react";
import {sendMessage} from "./api";
import {getChatTaskUrl, getChatUrl} from "./urls";


const ChatMessages = function(props) {
  let thinkingElement = '';
  if (props.hasPendingMessage) {
    const thinkingMessage = {
      content: <p className="add-loading-dots">Thinking</p>,
      message_type: "AI",
    }
    thinkingElement = <ChatMessage key="thinking-message" {...thinkingMessage} />
  }
  return (
    <div id="message-list" className="pg-chat-pane">
      {
        props.messages.map((message, index) => {
          return <ChatMessage key={message.id} index={index} {...message} />;
        })
      }
      {thinkingElement}
    </div>
  );
};

const ChatMessage = function(props) {
  if (props.message_type === "HUMAN") {
    return <HumanMessage {...props} />
  } else {
    return <AIMessage {...props} />
  }
}

const HumanMessage = function(props) {
  return (
    <div className="pg-chat-message-user">
      <div className="pg-chat-icon">
        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth="1.5"
             stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round"
                d="M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.501 20.118a7.5 7.5 0 0114.998 0A17.933 17.933 0 0112 21.75c-2.676 0-5.216-.584-7.499-1.632z"/>
        </svg>
      </div>
      <div className="pg-message-contents">
        {props.content}
      </div>
    </div>
  );
};

const AIMessage = function(props) {
  return (
    <div className="pg-chat-message-system">
      <div className="pg-chat-icon">
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
             strokeLinecap="round" strokeLinejoin="round">
          <path
            d="M7 7h10a2 2 0 0 1 2 2v1l1 1v3l-1 1v3a2 2 0 0 1 -2 2h-10a2 2 0 0 1 -2 -2v-3l-1 -1v-3l1 -1v-1a2 2 0 0 1 2 -2z"></path>
          <path d="M10 16h4"></path>
          <circle cx="8.5" cy="11.5" r=".5" fill="currentColor"></circle>
          <circle cx="15.5" cy="11.5" r=".5" fill="currentColor"></circle>
          <path d="M9 7l-1 -4"></path>
          <path d="M15 7l1 -4"></path>
        </svg>
      </div>
      <div className="pg-message-contents">
        {props.content}
      </div>
    </div>
  );
};

const InputBar = function(props) {
  const handleKeyPress = (event) => {
    if (event.key === 'Enter') {
      props.sendMessage(props.message);
    }
  }
  return (
    <div className="pg-chat-input-bar">
      <input name="message" type="text" placeholder="Type your message..." aria-label="Message" className="pg-control" value={props.message}
             onChange={(event) => props.setMessage(event.target.value)}
             onKeyPress={handleKeyPress}>

      </input>
      <button type="submit" className="pg-button-primary mx-2" onClick={() => props.sendMessage(props.message)}>Send</button>
    </div>
  );
}

function getWelcomeMessage() {
  return {
    id: 'welcome-message',
    message_type: "AI",
    content: "Hello, what can I help you with today?",
  };
}


function getErrorMessage() {
  return {
    id: `error-message-${Date.now()}`,
    message_type: "AI",
    content: <p className="pg-text-danger">
      Sorry, something went wrong while generating a response. Please try again.
      If you are a site administrator seeing this for the first time, check that the AI backend
      API key settings are configured correctly and restart all running processes.
    </p>
  };
}

const ChatApplication = function(props) {
  const [messages, setMessages] = useState([getWelcomeMessage(), ...props.chat.messages]);
  const [inputMessage, setInputMessage] = useState("");
  const [currentTaskId, setCurrentTaskId] = useState(null);

  useEffect(() => {
    // scroll to bottom on new messages
    const chatUI = document.getElementById('message-list');
    chatUI.scrollTop = chatUI.scrollHeight;
  }, [messages]);

  useEffect(() => {
    if (currentTaskId) {
      const taskUrl = getChatTaskUrl(props.apiUrls['chat:api_get_message_response'], props.chat.id, currentTaskId);
      let cancelled = false;
      let timerId = null;
      let failures = 0;
      const fetchData = async () => {
        if (cancelled) return;
        try {
          const response = await fetch(taskUrl);
          const jsonResponse = await response.json();
          if (cancelled) return;
          if (jsonResponse.complete) {
            if (jsonResponse.success) {
              addMessage(jsonResponse.result);
            } else {
              addMessage(getErrorMessage())
            }
            setCurrentTaskId(null);
          } else {
            timerId = window.setTimeout(fetchData, 1000);
          }
        } catch (error) {
          console.error('Fetch error:', error);
          if (cancelled) return;
          // Retry transient failures instead of leaving the chat stuck on
          // "Thinking..." forever; give up after a few attempts.
          failures += 1;
          if (failures < 5) {
            timerId = window.setTimeout(fetchData, 2000);
          } else {
            addMessage(getErrorMessage());
            setCurrentTaskId(null);
          }
        }
      };
      fetchData();
      return () => {
        cancelled = true;
        if (timerId) {
          window.clearTimeout(timerId);
        }
      };
    }
  }, [currentTaskId])

  const addMessage = (message) => {
    // Functional update: a stale closure here would drop messages that were
    // added while the response poll was in flight
    setMessages((prev) => [...prev, message]);
  }
  const inputChanged = (message) => {
    setInputMessage(message);
  }
  const sendMessageCallback = (responseData) => {
    setCurrentTaskId(responseData.task_id);
    addMessage(responseData);
    setInputMessage("");
  }
  const sendMessageError = () => {
    addMessage(getErrorMessage());
  }
  const sendMessageWrapper = (message) => {
    if (!message || !message.trim() || currentTaskId) {
      // Don't send empty messages or double-send while a response is pending
      return;
    }
    const apiUrl = getChatUrl(props.apiUrls['chat:api_new_chat_message'], props.chat.id)
    return sendMessage(apiUrl, props.chat.id, message, sendMessageCallback, sendMessageError);
  }
  return  (
    <>
      <ChatMessages messages={messages} hasPendingMessage={Boolean(currentTaskId)}/>
      <InputBar chat={props.chat} message={inputMessage} setMessage={inputChanged} sendMessage={sendMessageWrapper}/>
    </>
  );
}

export default ChatApplication;

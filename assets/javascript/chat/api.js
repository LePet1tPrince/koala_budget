import {Cookies} from "../app";
import {getChatUrl} from "./urls";


export const sendMessage = (apiUrl, chat_id, message, callBack, onError) => {
  const messageData = {
    chat: chat_id,
    message_type: "HUMAN",
    content: message,
  }
  return fetch(apiUrl, {
    method: "POST",
    credentials: 'same-origin',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': Cookies.get('csrftoken'),
    },
    body: JSON.stringify(messageData),
  }).then((response) => {
    if (!response.ok) {
      throw new Error(`Failed to send message (${response.status})`);
    }
    return response.json();
  }).then((data) => {
    callBack(data);
  }).catch((error) => {
    console.error('Failed to send chat message:', error);
    if (onError) {
      onError(error);
    }
  });
}

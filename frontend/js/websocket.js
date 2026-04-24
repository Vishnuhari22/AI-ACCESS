class UIAAWebSocket {
    constructor(url, onMessageCallback, onStatusChangeCallback) {
        this.url = url;
        this.ws = null;
        this.onMessageCallback = onMessageCallback;
        this.onStatusChangeCallback = onStatusChangeCallback;
        this.reconnectTimeout = null;
        this.reconnectDelay = 2000;
    }

    connect() {
        this.onStatusChangeCallback('connecting');
        this.ws = new WebSocket(this.url);

        this.ws.onopen = () => {
            this.onStatusChangeCallback('connected');
            if (this.reconnectTimeout) {
                clearTimeout(this.reconnectTimeout);
                this.reconnectTimeout = null;
            }
        };

        this.ws.onmessage = (event) => {
            this.onMessageCallback(event.data);
        };

        this.ws.onclose = () => {
            this.onStatusChangeCallback('disconnected');
            this.scheduleReconnect();
        };

        this.ws.onerror = (err) => {
            console.error('WebSocket Error:', err);
            this.ws.close();
        };
    }

    send(data) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(typeof data === 'string' ? data : JSON.stringify(data));
        } else {
            console.warn('Cannot send, WebSocket not open');
        }
    }

    scheduleReconnect() {
        if (!this.reconnectTimeout) {
            this.reconnectTimeout = setTimeout(() => {
                this.connect();
            }, this.reconnectDelay);
        }
    }
}

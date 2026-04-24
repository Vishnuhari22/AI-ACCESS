/**
 * Kiosk UI Renderer — dynamically renders kiosk screens based on 
 * state data received from the backend.
 * Phase 5: Polished with staggered animations, better visual hierarchy,
 * and screen-specific enhancements.
 */
class KioskRenderer {
    constructor(screenElementId) {
        this.screenEl = document.getElementById(screenElementId);
        this.currentScreenId = 'welcome';
        this.currentMode = 'atm';
    }

    /**
     * Render a kiosk screen from backend data.
     * @param {Object} screenData - {screen_id, title, description, buttons, input_field, display_data, mode}
     */
    render(screenData) {
        this.currentScreenId = screenData.screen_id;
        this.currentMode = screenData.mode;
        
        // Transition out
        this.screenEl.classList.add('screen-transitioning');
        
        setTimeout(() => {
            this.screenEl.innerHTML = '';
            
            const container = document.createElement('div');
            container.className = `kiosk-screen-content screen-${screenData.screen_id}`;

            // Screen icon
            const icon = document.createElement('div');
            icon.className = 'screen-icon';
            icon.textContent = this._getScreenIcon(screenData.screen_id, screenData.mode);
            container.appendChild(icon);

            // Title
            const title = document.createElement('h2');
            title.className = 'screen-title';
            title.textContent = screenData.title;
            container.appendChild(title);

            // Description
            if (screenData.description) {
                const desc = document.createElement('p');
                desc.className = 'screen-description';
                desc.textContent = screenData.description;
                container.appendChild(desc);
            }

            // Display data (balance, transactions, token, etc.)
            if (screenData.display_data && Object.keys(screenData.display_data).length > 0) {
                const dataEl = this._renderDisplayData(screenData.display_data, screenData.screen_id);
                if (dataEl) container.appendChild(dataEl);
            }

            // Input field (numpad/pin)
            if (screenData.input_field) {
                const inputEl = this._renderInputField(screenData.input_field);
                container.appendChild(inputEl);
            }

            // Buttons
            if (screenData.buttons && screenData.buttons.length > 0) {
                const btnGroup = document.createElement('div');
                btnGroup.className = 'kiosk-btn-group';
                
                for (let i = 0; i < screenData.buttons.length; i++) {
                    const btn = screenData.buttons[i];
                    const btnEl = document.createElement('button');
                    btnEl.className = 'kiosk-btn';
                    btnEl.textContent = btn.label;
                    btnEl.dataset.action = btn.action;
                    // Staggered animation
                    btnEl.style.animationDelay = `${0.25 + i * 0.05}s`;
                    
                    if (btn.action === 'GO_BACK' || btn.action === 'GO_HOME' || btn.action === 'NEW_TRANSACTION') {
                        btnEl.classList.add('kiosk-btn-secondary');
                    }
                    
                    btnGroup.appendChild(btnEl);
                }
                container.appendChild(btnGroup);
            }

            // Processing animation
            if (screenData.screen_id === 'processing') {
                const spinner = document.createElement('div');
                spinner.className = 'processing-spinner';
                spinner.innerHTML = '<div class="spinner"></div>';
                container.appendChild(spinner);

                // Auto-advance after 2 seconds
                setTimeout(() => {
                    this._onAutoAdvance('PROCESS_TRANSACTION');
                }, 2000);
            }

            // Dispensing screen — special animated cash display
            if (screenData.screen_id === 'dispensing') {
                const cashAnim = document.createElement('div');
                cashAnim.className = 'dispensing-animation';
                cashAnim.innerHTML = '<div class="cash-slot">💵💵💵</div>';
                container.appendChild(cashAnim);
            }

            // Thank you — auto-reset timer hint
            if (screenData.screen_id === 'thank_you') {
                const hint = document.createElement('p');
                hint.className = 'screen-hint';
                hint.textContent = 'This screen will reset in 10 seconds, or click a button.';
                container.appendChild(hint);
            }

            this.screenEl.appendChild(container);
            this.screenEl.classList.remove('screen-transitioning');

            // Trigger kiosk frame glow on adaptation
            const frame = document.querySelector('.kiosk-frame');
            if (frame) {
                frame.classList.add('adapting');
                setTimeout(() => frame.classList.remove('adapting'), 1000);
            }
        }, 200);
    }

    _getScreenIcon(screenId, mode) {
        const icons = {
            // ATM
            welcome: mode === 'atm' ? '🏧' : '🏥',
            main_menu: '📋',
            withdrawal: '💵',
            enter_amount: '🔢',
            enter_pin: '🔒',
            processing: '⏳',
            dispensing: '💸',
            receipt: '🧾',
            balance_display: '💰',
            statement_display: '📄',
            thank_you: '✅',
            // Hospital
            department_select: '🏥',
            doctor_select: '👨‍⚕️',
            token_generated: '🎫',
            appointment_check: '📅',
            appointment_details: '📋',
        };
        return icons[screenId] || '📱';
    }

    _renderDisplayData(data, screenId) {
        const wrapper = document.createElement('div');
        wrapper.className = 'display-data';

        // Balance display
        if (data.balance) {
            const bal = document.createElement('div');
            bal.className = 'balance-display';
            bal.innerHTML = `
                <div class="balance-label">Available Balance</div>
                <div class="balance-amount">${data.balance}</div>
                <div class="balance-account">${data.account || ''}</div>
            `;
            wrapper.appendChild(bal);
        }

        // Transaction statement
        if (data.transactions) {
            const table = document.createElement('div');
            table.className = 'statement-table';
            for (let i = 0; i < data.transactions.length; i++) {
                const tx = data.transactions[i];
                const row = document.createElement('div');
                row.className = 'statement-row';
                row.style.animationDelay = `${i * 0.05}s`;
                const isCredit = tx.amount.startsWith('+');
                row.innerHTML = `
                    <span class="tx-date">${tx.date}</span>
                    <span class="tx-desc">${tx.desc}</span>
                    <span class="tx-amount ${isCredit ? 'credit' : 'debit'}">${tx.amount}</span>
                `;
                table.appendChild(row);
            }
            wrapper.appendChild(table);
        }

        // Token display
        if (data.token_number && screenId === 'token_generated') {
            const token = document.createElement('div');
            token.className = 'token-display';
            token.innerHTML = `
                <div class="token-label">Your Token Number</div>
                <div class="token-number">${data.token_number}</div>
                ${data.department ? `<div class="token-dept">Department: ${data.department}</div>` : ''}
                ${data.doctor ? `<div class="token-doctor">Doctor: ${data.doctor}</div>` : ''}
            `;
            wrapper.appendChild(token);
        }

        // Withdrawal amount
        if (data.amount && (screenId === 'enter_pin' || screenId === 'dispensing' || screenId === 'processing')) {
            const amtEl = document.createElement('div');
            amtEl.className = 'amount-display';
            amtEl.innerHTML = `<div class="amount-label">Amount</div><div class="amount-value">₹${data.amount.toLocaleString()}</div>`;
            wrapper.appendChild(amtEl);
        }

        // Doctors list
        if (data.doctors) {
            const list = document.createElement('div');
            list.className = 'doctor-list';
            for (let i = 0; i < data.doctors.length; i++) {
                const doc = data.doctors[i];
                const card = document.createElement('div');
                card.className = 'doctor-card';
                card.dataset.action = doc.action;
                card.style.animationDelay = `${0.15 + i * 0.08}s`;
                card.innerHTML = `
                    <div class="doctor-name">👨‍⚕️ ${doc.name}</div>
                    <div class="doctor-slots">Available: ${doc.slots}</div>
                `;
                list.appendChild(card);
            }
            wrapper.appendChild(list);
        }

        // Appointment details
        if (data.appointment) {
            const appt = data.appointment;
            const el = document.createElement('div');
            el.className = 'appointment-display';
            el.innerHTML = `
                <div class="appt-row"><strong>Doctor:</strong> ${appt.doctor}</div>
                <div class="appt-row"><strong>Department:</strong> ${appt.dept}</div>
                <div class="appt-row"><strong>Date:</strong> ${appt.date}</div>
                <div class="appt-row"><strong>Time:</strong> ${appt.time}</div>
                <div class="appt-status">${appt.status}</div>
            `;
            wrapper.appendChild(el);
        }

        return wrapper.children.length > 0 ? wrapper : null;
    }

    _renderInputField(inputField) {
        const wrapper = document.createElement('div');
        wrapper.className = 'input-field-wrapper';

        const display = document.createElement('div');
        display.className = 'input-display';
        display.id = 'kiosk-input-display';
        display.textContent = inputField.placeholder;
        wrapper.appendChild(display);

        // Numpad
        const numpad = document.createElement('div');
        numpad.className = 'numpad';
        const keys = inputField.type === 'pin' 
            ? ['1','2','3','4','5','6','7','8','9','','0','⌫']
            : ['1','2','3','4','5','6','7','8','9','00','0','⌫'];
        
        for (const key of keys) {
            const btn = document.createElement('button');
            btn.className = 'numpad-key';
            btn.textContent = key;
            if (key === '') {
                btn.disabled = true;
                btn.style.visibility = 'hidden';
            }
            btn.dataset.key = key;
            numpad.appendChild(btn);
        }

        wrapper.appendChild(numpad);
        return wrapper;
    }

    // Callback for auto-advance (e.g., processing → dispensing)
    _onAutoAdvance(command) {
        if (this.onAutoAdvance) {
            this.onAutoAdvance(command);
        }
    }
}

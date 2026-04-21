(function () {
    function defaultWrapper(input) {
        return input.closest("[data-field-wrapper]") || input.closest(".field") || input.closest(".portal-field") || input.parentElement;
    }

    function ensureErrorNode(wrapper) {
        if (!wrapper) {
            return null;
        }
        let node = wrapper.querySelector(".field-error");
        if (!node) {
            node = document.createElement("div");
            node.className = "field-error";
            wrapper.appendChild(node);
        }
        return node;
    }

    function ensureModal() {
        let backdrop = document.getElementById("validation-modal");
        if (backdrop) {
            return backdrop;
        }
        backdrop = document.createElement("div");
        backdrop.id = "validation-modal";
        backdrop.style.cssText = "position:fixed;inset:0;background:rgba(15,23,42,.45);display:none;align-items:center;justify-content:center;padding:20px;z-index:2000;";
        backdrop.innerHTML = [
            '<div style="width:min(520px,100%);background:#fff;border-radius:20px;border:1px solid #dbe6f2;box-shadow:0 24px 60px rgba(15,23,42,.2);overflow:hidden;">',
            '<div style="padding:18px 20px;border-bottom:1px solid #e7eef6;background:linear-gradient(180deg,#fff,#f8fbff);display:flex;justify-content:space-between;gap:12px;align-items:center;">',
            '<div><div style="font-size:16px;font-weight:700;color:#16243d;">Please fix the highlighted fields</div>',
            '<div style="font-size:12px;color:#7b8ba4;margin-top:4px;">Validation runs before submit and again on the server for security.</div></div>',
            '<button type="button" data-close-validation-modal style="border:none;background:transparent;font-size:24px;line-height:1;color:#64748b;cursor:pointer;">&times;</button>',
            '</div>',
            '<div style="padding:18px 20px;display:grid;gap:10px;"><ul data-validation-modal-list style="margin:0;padding-left:18px;color:#b42318;font-size:13px;line-height:1.55;"></ul></div>',
            '<div style="padding:16px 20px;border-top:1px solid #e7eef6;background:#fbfdff;display:flex;justify-content:flex-end;gap:10px;">',
            '<button type="button" data-close-validation-modal style="min-height:42px;padding:0 16px;border-radius:12px;border:1px solid #d9e4f0;background:#fff;color:#1e293b;font:inherit;font-weight:700;cursor:pointer;">Close</button>',
            '</div></div>',
        ].join("");
        document.body.appendChild(backdrop);
        backdrop.addEventListener("click", function (event) {
            if (event.target === backdrop || event.target.hasAttribute("data-close-validation-modal")) {
                backdrop.style.display = "none";
            }
        });
        return backdrop;
    }

    function showModal(messages) {
        const modal = ensureModal();
        const list = modal.querySelector("[data-validation-modal-list]");
        list.innerHTML = "";
        messages.forEach(function (message) {
            const item = document.createElement("li");
            item.textContent = message;
            list.appendChild(item);
        });
        modal.style.display = "flex";
    }

    function normalizeValue(input) {
        if (!input) {
            return "";
        }
        if (input.type === "checkbox" || input.type === "radio") {
            return input.checked ? "1" : "";
        }
        if (input.type === "file") {
            return input.files && input.files.length ? input.files[0].name : "";
        }
        return (input.value || "").trim();
    }

    function parseRule(input, explicitRule) {
        const rule = explicitRule || {};
        if (input.dataset.required === "true") {
            rule.required = true;
        }
        if (input.dataset.validateEmail === "true") {
            rule.email = true;
        }
        if (input.dataset.validateDigits === "true") {
            rule.digits = true;
        }
        if (input.dataset.validateDate === "true") {
            rule.date = true;
        }
        if (input.dataset.minLength) {
            rule.minLength = Number(input.dataset.minLength);
        }
        if (input.dataset.maxLength) {
            rule.maxLength = Number(input.dataset.maxLength);
        }
        if (input.dataset.matches) {
            rule.matches = input.dataset.matches;
        }
        if (input.dataset.message && !rule.message) {
            rule.message = input.dataset.message;
        }
        if (input.dataset.label && !rule.label) {
            rule.label = input.dataset.label;
        }
        return rule;
    }

    function buildMessage(input, rule, failure) {
        if (failure === "required") {
            return "This field is required.";
        }
        if (failure === "email") {
            return "Email must be in valid format (example@domain.com).";
        }
        if (failure === "digits") {
            return "Mobile number must contain only digits.";
        }
        if (failure === "date") {
            return "Date must be valid and in the correct format.";
        }
        if (failure === "minLength") {
            return (rule.label || "This field") + " must be at least " + rule.minLength + " characters.";
        }
        if (failure === "maxLength") {
            return (rule.label || "This field") + " must be " + rule.maxLength + " characters or fewer.";
        }
        if (failure === "matches") {
            return rule.message || "Values do not match.";
        }
        return rule.message || "Please correct this field.";
    }

    function validateInput(input, explicitRule, config) {
        const rule = parseRule(input, explicitRule);
        const wrapper = (config && config.wrapperFor ? config.wrapperFor(input) : defaultWrapper(input));
        const errorNode = ensureErrorNode(wrapper);
        const value = normalizeValue(input);
        let message = "";

        if (typeof rule.custom === "function") {
            message = rule.custom(input, value) || "";
        } else if (rule.required && !value) {
            message = buildMessage(input, rule, "required");
        } else if (value) {
            if (rule.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)) {
                message = buildMessage(input, rule, "email");
            } else if (rule.digits && !/^\d+$/.test(value.replace(/\s+/g, ""))) {
                message = buildMessage(input, rule, "digits");
            } else if (rule.date && Number.isNaN(Date.parse(value))) {
                message = buildMessage(input, rule, "date");
            } else if (rule.minLength && value.length < rule.minLength) {
                message = buildMessage(input, rule, "minLength");
            } else if (rule.maxLength && value.length > rule.maxLength) {
                message = buildMessage(input, rule, "maxLength");
            } else if (rule.matches) {
                const other = document.getElementById(rule.matches);
                if (other && value !== normalizeValue(other)) {
                    message = buildMessage(input, rule, "matches");
                }
            }
        }

        if (wrapper) {
            wrapper.classList.toggle("is-invalid", Boolean(message));
        }
        if (input) {
            input.setAttribute("aria-invalid", message ? "true" : "false");
            input.style.borderColor = message ? "rgba(163,52,52,.45)" : "";
            input.style.boxShadow = message ? "0 0 0 4px rgba(163,52,52,.08)" : "";
        }
        if (errorNode) {
            errorNode.textContent = message;
        }
        return message;
    }

    window.BMISFormValidation = {
        init: function (form, config) {
            if (!form) {
                return;
            }
            const rules = (config && config.rules) || {};
            const inputs = Object.keys(rules).map(function (id) {
                return document.getElementById(id);
            }).filter(Boolean);

            inputs.forEach(function (input) {
                ["input", "change", "blur"].forEach(function (eventName) {
                    input.addEventListener(eventName, function () {
                        validateInput(input, rules[input.id], config);
                    });
                });
            });

            form.addEventListener("submit", function (event) {
                const messages = [];
                let firstInvalid = null;
                inputs.forEach(function (input) {
                    const message = validateInput(input, rules[input.id], config);
                    if (message) {
                        messages.push(message);
                        if (!firstInvalid) {
                            firstInvalid = input;
                        }
                    }
                });
                if (messages.length) {
                    event.preventDefault();
                    showModal(Array.from(new Set(messages)));
                    if (firstInvalid) {
                        firstInvalid.focus();
                    }
                }
            });
        },
        validateInput: validateInput,
        showModal: showModal,
    };
}());

// Adapted from https://developer.mozilla.org/en-US/docs/Web/API/WindowBase64.btoa

var Base64 =
{
    // If passed string is UTF-8, decodes to bytes first before encoding.
    encode: function (str) {
        return window.btoa(unescape(encodeURIComponent(str)));
    },

    // Returns a UTF-8 string if input is UTF-8, raw bytes otherwise.
    decode: function (str) {
        return decodeURIComponent(escape(window.atob(str)));
    }
};

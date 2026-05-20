/****************************************************************************
**
** Copyright (C) 2016 The Qt Company Ltd.
** Contact: https://www.qt.io/licensing/
**
** This file is part of the QtWebChannel module of the Qt Toolkit.
**
** $QT_BEGIN_LICENSE:LGPL$
** Commercial License Usage
** Licensees holding valid commercial Qt licenses may use this file in
** accordance with the commercial license agreement provided with the
** Software or, alternatively, in accordance with the terms contained in
** a written agreement between you and The Qt Company. For licensing terms
** and conditions see https://www.qt.io/terms-conditions. For further
** information use the contact form at https://www.qt.io/contact-us.
**
** GNU Lesser General Public License Usage
** Alternatively, this file may be used under the terms of the GNU Lesser
** General Public License version 3 as published by the Free Software
** Foundation and appearing in the file LICENSE.LGPL3 included in the
** packaging of this file. Please review the following information to
** ensure the GNU Lesser General Public License version 3 requirements
** will be met: https://www.gnu.org/licenses/lgpl-3.0.html.
**
** GNU General Public License Usage
** Alternatively, this file may be used under the terms of the GNU
** General Public License version 2.0 or (at your option) the GNU General
** Public license version 3 or any later version approved by the KDE Free
** Qt Foundation. The licenses are as published by the Free Software
** Foundation and appearing in the file LICENSE.GPL2 and LICENSE.GPL3
** included in the packaging of this file. Please review the following
** information to ensure the GNU General Public License requirements will
** be met: https://www.gnu.org/licenses/gpl-2.0.html and
** https://www.gnu.org/licenses/gpl-3.0.html.
**
** $QT_END_LICENSE$
**
****************************************************************************/

"use strict";

var QWebChannelMessageTypes = {
    signal: 1,
    propertyUpdate: 2,
    init: 3,
    idle: 4,
    debug: 5,
    invokeMethod: 6,
    connectToSignal: 7,
    disconnectFromSignal: 8,
    setProperty: 9,
    response: 10,
};

var QWebChannel = function(transport, initCallback)
{
    if (typeof transport !== "object") {
        console.error("The QWebChannel requires a transport object");
        return;
    }

    var channel = this;
    this.transport = transport;

    function send(data)
    {
        if (typeof(data) !== "string") {
            data = JSON.stringify(data);
        }
        channel.transport.send(data);
    }

    this.transport.onmessage = function(message)
    {
        var data = message.data;
        if (typeof data === "string") {
            data = JSON.parse(data);
        }
        switch (data.type) {
            case QWebChannelMessageTypes.signal:
                channel.handleSignal(data);
                break;
            case QWebChannelMessageTypes.response:
                channel.handleResponse(data);
                break;
            case QWebChannelMessageTypes.propertyUpdate:
                channel.handlePropertyUpdate(data);
                break;
            default:
                console.error("invalid message received:", message.data);
                break;
        }
    }

    this.execCallbacks = {};
    this.execId = 0;
    this.exec = function(data, callback)
    {
        if (!callback) {
            callback = function() {};
        }
        if (data.id === undefined) {
            data.id = channel.execId++;
        }
        channel.execCallbacks[data.id] = callback;
        send(data);
    };

    this.objects = {};

    this.handleSignal = function(data)
    {
        var object = channel.objects[data.object];
        if (object) {
            object.signalEmitted(data.signal, data.args);
        } else {
            console.warn("Unhandled signal: " + data.object + "::" + data.signal);
        }
    }

    this.handleResponse = function(data)
    {
        if (data.id === undefined || data.id === null) {
            console.error("invalid response message received: ", JSON.stringify(data));
            return;
        }
        var callback = channel.execCallbacks[data.id];
        if (callback) {
            delete channel.execCallbacks[data.id];
            callback(data.data);
        } else {
            console.error("no callback for response message: ", JSON.stringify(data));
        }
    }

    this.handlePropertyUpdate = function(data)
    {
        for (var i = 0; i < data.data.length; ++i) {
            var update = data.data[i];
            var object = channel.objects[update.object];
            if (object) {
                object.propertyUpdate(update.signals, update.properties);
            } else {
                console.warn("Unhandled property update: " + update.object + "::" + update.signal);
            }
        }
        channel.exec({type: QWebChannelMessageTypes.idle});
    }

    this.debug = function(message)
    {
        channel.exec({type: QWebChannelMessageTypes.debug, data: message});
    };

    channel.exec({type: QWebChannelMessageTypes.init}, function(data) {
        for (var objectName in data) {
            var object = new QObject(objectName, data[objectName], channel);
        }
        if (initCallback) {
            initCallback(channel);
        }
        channel.exec({type: QWebChannelMessageTypes.idle});
    });
};

function QObject(name, data, channel)
{
    this.__id__ = name;
    channel.objects[name] = this;
    this.__objectSignals__ = {};
    this.__propertyCache__ = {};

    var object = this;

    this.unwrapQObject = function(response)
    {
        if (response instanceof Array) {
            var ret = new Array(response.length);
            for (var i = 0; i < response.length; ++i) {
                ret[i] = object.unwrapQObject(response[i]);
            }
            return ret;
        }
        if (!(response instanceof Object))
            return response;

        if (!response["__QObject*__"] || response.id === undefined) {
            var jObj = {};
            for (var propName in response) {
                jObj[propName] = object.unwrapQObject(response[propName]);
            }
            return jObj;
        }

        var objectId = response.id;
        if (channel.objects[objectId])
            return channel.objects[objectId];

        if (!response.data) {
            console.error("Cannot unwrap unknown QObject " + objectId + " without data.");
            return;
        }

        var qObject = new QObject(objectId, response.data, channel);
        return qObject;
    }

    this.signalEmitted = function(signalName, signalArgs)
    {
        var connections = object.__objectSignals__[signalName];
        if (connections) {
            connections.forEach(function(callback) {
                callback.apply(callback, signalArgs);
            });
        }
    }

    this.propertyUpdate = function(signals, propertyMap)
    {
        for (var propertyName in propertyMap) {
            object.__propertyCache__[propertyName] = propertyMap[propertyName];
        }
        for (var signalName in signals) {
            object.signalEmitted(signalName, signals[signalName]);
        }
    }

    this.connect = function(signalName, callback)
    {
        if (!object.__objectSignals__[signalName]) {
            object.__objectSignals__[signalName] = [];
            channel.exec({type: QWebChannelMessageTypes.connectToSignal, object: object.__id__, signal: signalName});
        }
        object.__objectSignals__[signalName].push(callback);
    }

    this.disconnect = function(signalName, callback)
    {
        if (!object.__objectSignals__[signalName]) {
            return;
        }
        var idx = object.__objectSignals__[signalName].indexOf(callback);
        if (idx === -1) {
            return;
        }
        object.__objectSignals__[signalName].splice(idx, 1);
        if (object.__objectSignals__[signalName].length === 0) {
            delete object.__objectSignals__[signalName];
            channel.exec({type: QWebChannelMessageTypes.disconnectFromSignal, object: object.__id__, signal: signalName});
        }
    }

    var methods = data.methods;
    for (var methodName in methods) {
        (function(methodName) {
            object[methodName] = function() {
                var args = [];
                for (var i = 0; i < arguments.length; ++i) {
                    args.push(arguments[i]);
                }
                var callback;
                if (args.length > 0 && typeof args[args.length - 1] === "function") {
                    callback = args.pop();
                }
                channel.exec({type: QWebChannelMessageTypes.invokeMethod, object: object.__id__, method: methodName, args: args}, function(response) {
                    if (response !== undefined) {
                        response = object.unwrapQObject(response);
                    }
                    if (callback) {
                        callback(response);
                    }
                });
            };
        })(methodName);
    }

    var properties = data.properties;
    for (var propertyName in properties) {
        (function(propertyName) {
            Object.defineProperty(object, propertyName, {
                get: function() {
                    var propertyValue = object.__propertyCache__[propertyName];
                    if (propertyValue === undefined) {
                        console.warn("Property '" + propertyName + "' is not yet cached.");
                    }
                    return propertyValue;
                },
                set: function(value) {
                    channel.exec({type: QWebChannelMessageTypes.setProperty, object: object.__id__, property: propertyName, value: value});
                }
            });
        })(propertyName);
    }
}
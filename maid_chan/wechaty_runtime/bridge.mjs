/**
 * JSON Lines bridge between the Python Wechaty transport and a Wechaty bot.
 *
 * Commands arrive as one JSON object per stdin line. Events and command results
 * are emitted as one JSON object per stdout line; human-readable QR codes use
 * stderr so they cannot corrupt the protocol stream.
 */
import readline from 'node:readline'
import process from 'node:process'
import { FileBox } from 'file-box'
import qrTerminal from 'qrcode-terminal'
import { ScanStatus, WechatyBuilder } from 'wechaty'

/**
 * Emit one structured bridge event on the stdout protocol stream.
 *
 * @param {Record<string, unknown>} payload - Event or command-result payload.
 * @returns {void}
 */
const emit = (payload) => {
  process.stdout.write(`${JSON.stringify(payload)}\n`)
}

const bot = WechatyBuilder.build({
  name: 'MaidChanWechaty',
  puppet: 'wechaty-puppet-wechat4u',
  puppetOptions: {
    uos: true,
  },
})

let stopping = false

/**
 * Persist available Wechaty state, close stdin, and terminate the bridge once.
 *
 * @param {number} [exitCode=0] - Process exit code to report to Python.
 * @returns {Promise<void>} Resolves only when a concurrent stop is in progress.
 */
async function stop(exitCode = 0) {
  if (stopping) return
  stopping = true
  try {
    await bot.puppet?.memory?.save()
    await bot.memory?.save()
  } catch (error) {
    emit({ type: 'error', operation: 'save-before-stop', message: String(error) })
  }
  commands.close()
  process.stdin.pause()
  process.stdin.unref?.()
  await new Promise((resolve) => setTimeout(resolve, 50))
  process.exit(exitCode)
}

bot.on('scan', (qrcode, status) => {
  if (status === ScanStatus.Waiting || status === ScanStatus.Timeout) {
    if (process.env.MAID_CHAN_RENDER_QR !== 'false') {
      qrTerminal.generate(qrcode, { small: true }, (rendered) => {
        process.stderr.write(`${rendered}\n`)
      })
    }
  }
  emit({
    type: 'scan',
    qrcode,
    status,
    statusName: ScanStatus[status] || String(status),
  })
})

bot.on('login', (user) => {
  emit({
    type: 'login',
    user: {
      id: user.id,
      name: user.name(),
    },
  })
})

bot.on('logout', (user) => {
  emit({
    type: 'logout',
    user: {
      id: user.id,
      name: user.name(),
    },
  })
})

bot.on('message', async (message) => {
  try {
    const talker = message.talker()
    if (!talker || talker.self()) return
    if (message.type() !== bot.Message.Type.Text) return
    const room = message.room()
    const alias = (await talker.alias()) || ''
    emit({
      type: 'message',
      id: message.id,
      text: message.text(),
      contact: {
        id: talker.id,
        name: talker.name(),
        alias,
      },
      room: room
        ? {
            id: room.id,
            topic: await room.topic(),
          }
        : null,
    })
  } catch (error) {
    emit({ type: 'error', operation: 'receive', message: String(error) })
  }
})

bot.on('error', (error) => {
  emit({ type: 'error', operation: 'wechaty', message: String(error) })
})

const commands = readline.createInterface({
  input: process.stdin,
  crlfDelay: Infinity,
})

commands.on('line', async (line) => {
  let command
  try {
    command = JSON.parse(line)
  } catch {
    emit({ type: 'error', operation: 'command', message: 'invalid JSON command' })
    return
  }

  const requestId = command.requestId || ''
  try {
    if (command.type === 'stop') {
      emit({ type: 'result', requestId, ok: true })
      await stop()
      return
    }
    if (command.type === 'logout') {
      const puppet = bot.puppet
      const webClient = puppet?.wechat4u
      let remoteAttempted = false
      let remoteResult = 'not logged in'
      if (bot.isLoggedIn && webClient?.logout) {
        remoteAttempted = true
        remoteResult = String(await webClient.logout())
      }
      if (bot.isLoggedIn) {
        await bot.logout()
      }
      if (puppet?.memory) {
        await puppet.memory.delete('PUPPET-WECHAT4U')
        await puppet.memory.save()
      }
      emit({
        type: 'result',
        requestId,
        ok: true,
        remoteAttempted,
        remoteResult,
        credentialsCleared: true,
      })
      return
    }
    if (command.type === 'send') {
      const contact = bot.Contact.load(String(command.contactId || ''))
      await contact.ready()
      await contact.say(String(command.text || ''))
      emit({ type: 'result', requestId, ok: true })
      return
    }
    if (command.type === 'sendName') {
      const wanted = String(command.name || '')
      let matches = await bot.Contact.findAll({ alias: wanted })
      if (!matches.length) {
        matches = await bot.Contact.findAll({ name: wanted })
      }
      if (matches.length !== 1) {
        throw new Error(
          matches.length
            ? `contact name is ambiguous: ${wanted}`
            : `contact not found: ${wanted}`,
        )
      }
      const text = String(command.text || '')
      const files = Array.isArray(command.files)
        ? command.files.map((item) => String(item))
        : []
      let sent = 0
      if (text) {
        await matches[0].say(text)
        sent += 1
      }
      for (const path of files) {
        await matches[0].say(FileBox.fromFile(path))
        sent += 1
      }
      if (!sent) {
        throw new Error('sendName requires text or files')
      }
      emit({ type: 'result', requestId, ok: true, sent })
      return
    }
    throw new Error(`unsupported command: ${command.type}`)
  } catch (error) {
    emit({
      type: 'result',
      requestId,
      ok: false,
      error: String(error),
    })
  }
})

process.on('SIGINT', () => void stop())
process.on('SIGTERM', () => void stop())

try {
  await bot.start()
  emit({ type: 'started' })
} catch (error) {
  emit({ type: 'fatal', message: String(error) })
  await stop(1)
}

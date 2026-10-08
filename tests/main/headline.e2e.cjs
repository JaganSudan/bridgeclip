const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const { buildApp, launchApp } = require('../zernio/support/electron-app.cjs')

test('headline and caption switches submit independently and keep the choice for another video', { timeout: 90000 }, async t => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'bridgeclip-headline-'))
  const session = await launchApp({ appDir: buildApp(path.join(root, 'app')), userDataDir: path.join(root, 'user-data') })
  t.after(async () => { await session.close(); fs.rmSync(root, { recursive: true, force: true }) })
  const { app, page } = session
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await app.evaluate(({ ipcMain }, root) => {
    globalThis.headlineRequests = []
    ipcMain.removeHandler('settings:load')
    ipcMain.handle('settings:load', () => ({ openrouterConfigured: true, zernioConfigured: false, outputDirectory: root, pythonPath: '', customVocabulary: '' }))
    ipcMain.removeHandler('system:checkTools')
    ipcMain.handle('system:checkTools', () => ({ python: true, pythonDeps: true, ffmpeg: true, ffmpegCaptions: true, ffprobe: true, ytdlp: true, engine: true, bridgeRunner: true }))
    ipcMain.removeHandler('job:start')
    ipcMain.handle('job:start', (_event, request) => {
      globalThis.headlineRequests.push(request)
      return { jobId: `headline-${globalThis.headlineRequests.length}`, queued: false }
    })
  }, root)
  await page.reload()
  const steps = page.getByRole('navigation', { name: 'Create steps' })
  const headline = page.getByRole('switch', { name: 'Burn in headline', exact: true })
  const captions = page.getByRole('switch', { name: 'Captions', exact: true })
  const selectVideo = async workflow => {
    await page.getByRole('radio', { name: workflow, exact: true }).click()
    await page.getByPlaceholder('YouTube, Twitch VOD or direct video link').fill('https://example.com/video.mp4')
    await page.getByRole('button', { name: 'Use link', exact: true }).click()
    await steps.getByRole('button').nth(3).click()
  }
  await selectVideo('Automatic')
  assert.equal(await headline.getAttribute('aria-checked'), 'false')
  assert.equal(await captions.getAttribute('aria-checked'), 'true')
  for (const [includeTitle, includeCaptions] of [[false, true], [true, true], [true, false], [false, false]]) {
    for (const [control, enabled] of [[headline, includeTitle], [captions, includeCaptions]]) {
      if (await control.getAttribute('aria-checked') !== String(enabled)) await control.click()
    }
    await steps.getByRole('button').nth(4).click()
    const row = page.locator('dl > div').filter({ has: page.locator('dt', { hasText: /^Headline$/ }) })
    assert.equal(await row.locator('dd').innerText(), includeTitle ? 'Burned in' : 'Off')
    await page.getByRole('button', { name: 'Generate clips', exact: true }).click()
    await page.getByRole('button', { name: 'Clip another video' }).waitFor()
    const request = await app.evaluate(() => globalThis.headlineRequests.at(-1))
    assert.equal(request.includeTitle, includeTitle)
    assert.equal(request.includeCaptions, includeCaptions)
    await page.getByRole('button', { name: 'Clip another video' }).click()
    await selectVideo('Automatic')
    assert.equal(await headline.getAttribute('aria-checked'), String(includeTitle))
    assert.equal(await captions.getAttribute('aria-checked'), String(includeCaptions))
  }
  await captions.click()
  for (const [width, height] of [[1280, 860], [720, 700]]) {
    await app.evaluate(({ BrowserWindow }, size) => BrowserWindow.getAllWindows()[0].setSize(...size), [width, height])
    await page.waitForFunction(width => window.innerWidth === width, width)
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true)
    const switchBox = await headline.boundingBox()
    assert.ok(switchBox.width > 0 && switchBox.x + switchBox.width <= width)
    if (process.env.BRIDGECLIP_E2E_SHOTS) {
      fs.mkdirSync(process.env.BRIDGECLIP_E2E_SHOTS, { recursive: true })
      await page.screenshot({ path: path.join(process.env.BRIDGECLIP_E2E_SHOTS, `headline-${width}.png`) })
    }
  }
  await steps.getByRole('button').nth(0).click()
  await page.getByRole('radio', { name: 'Review & edit', exact: true }).click()
  await steps.getByRole('button').nth(3).click()
  assert.equal(await headline.count(), 0)
  assert.deepEqual(errors, [])
})

// Names the slowest tests at the end of every vitest run, the way pytest's `--durations` does. vitest.config.js loads it.
//
// It is a plugin rather than an entry in `reporters`: naming any reporter there stops vitest from choosing its own, and
// vitest chooses the quiet `agent` reporter when an AI agent runs the tests (passing tests are not printed at all, so a
// slowTestThreshold line never shows to the agents that most need it). The plugin adds this reporter after vitest has
// chosen, so people keep the default reporter and agents keep the quiet one, and both see the slowest tests.

const SLOWEST_COUNT = 10

class SlowestTestsReporter {
  onInit(vitest) {
    this.vitest = vitest
  }

  onTestRunEnd(testModules) {
    const timed = []
    for (const testModule of testModules) {
      for (const test of testModule.children.allTests()) {
        const duration = test.diagnostic()?.duration
        if (duration != null) timed.push({ duration, name: `${testModule.relativeModuleId} > ${test.fullName}` })
      }
    }
    if (!timed.length) return
    timed.sort((a, b) => b.duration - a.duration)
    const lines = timed.slice(0, SLOWEST_COUNT).map(({ duration, name }) => `${String(Math.round(duration)).padStart(7)} ms  ${name}`)
    this.vitest.logger.log(`\nslowest ${lines.length} tests\n${lines.join('\n')}`)
  }
}

export function slowestTestsPlugin() {
  return {
    name: 'cpc-slowest-tests',
    configureVitest({ vitest }) {
      vitest.config.reporters.push(new SlowestTestsReporter())
    },
  }
}

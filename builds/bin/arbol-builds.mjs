#!/usr/bin/env node
import { main } from '../../dist/builds/cli.js';
process.exitCode = await main(process.argv.slice(2));
